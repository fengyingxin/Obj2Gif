import numpy as np
import trimesh
import pyrender
import os
import imageio
import argparse
from skimage.color import rgb2hsv, hsv2rgb

def init_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--obj_path", type=str, required=True)
    parser.add_argument("--gif_path", type=str, required=True)
    parser.add_argument("--frames_folder_path", type=str, required=True)
    parser.add_argument("--image_width", type=int, default=640)
    parser.add_argument("--image_height", type=int, default=640)
    parser.add_argument("--num_frames", type=int, default=36,
                        help="number of rendered images to create the GIF")
    parser.add_argument("--image_duration", type=float, default=0.1,
                        help="duration of each image in the GIF")
    parser.add_argument("--image_loops", type=float, default=0,
                        help="number of loops in the GIF (set as 0 to allow looping endlessly)")
    parser.add_argument("--set_initial_camera_pose", type=bool, default=False)
    parser.add_argument("--camera_pose", type=str,
                        default="[[1.0,0.0,0.0,0.0],[0.0,1.0,0.0,0.0],[0.0,0.0,1.0,0.0],[0.0,0.0,0.0,1.0]]",
                        help="camera pose (4*4 matrix) for the first image in the GIF")
    parser.add_argument("--light_intensity", type=float, default=3.0,
                        help="brightness of light, in lux (lm/m^2).")
    parser.add_argument("--light_color", type=str, default="[1.0,1.0,1.0]",
                        help="RGB value for the light’s color in linear space")
    parser.add_argument("--image_saturation", type=float, default=1.0,
                        help="saturation factor of the GIF. It's observed that sometimes rendered images are lower in saturation than expected")


    args = parser.parse_args()
    # preprocess camera_pose to correct format
    if args.set_initial_camera_pose:
        args.camera_pose=eval(args.camera_pose)
        args.camera_pose=np.array(args.camera_pose)
    args.light_color = eval(args.light_color)
    return args

def init_scene(args):
    # load mesh to the scene
    mesh_trimesh = trimesh.load(args.obj_path)
    mesh_pyrender = pyrender.Mesh.from_trimesh(mesh_trimesh)
    scene = pyrender.Scene()
    mesh_node = scene.add(mesh_pyrender)
    return scene,mesh_node

def change_parameters(args):
    # initialize scene
    scene, mesh_node=init_scene(args)

    # set up the initial camera pose (if any)
    if args.set_initial_camera_pose:
        camera = pyrender.PerspectiveCamera(yfov=np.pi / 3.0)
        scene.add(camera, pose=args.camera_pose)

    # set up the initial light
    light = pyrender.DirectionalLight(color=args.light_color, intensity=args.light_intensity)
    if args.set_initial_camera_pose:
        light_node = scene.add(light, pose=args.camera_pose)
    else:
        light_node = scene.add(light)

    # initialize the viewer
    viewer = pyrender.Viewer(scene, use_raymond_lighting=True, run_in_thread=True,viewport_size=(args.image_width,args.image_height))

    # choose the camera pose from the viewer
    input("Adjust the camera in the viewer, then press Enter to get the camera pose...")
    camera_nodes = [node for node in scene.get_nodes() if isinstance(node.camera, pyrender.PerspectiveCamera)]
    if args.set_initial_camera_pose:
        if np.abs(np.sum(np.abs(np.array(camera_nodes[0].matrix))-np.abs(args.camera_pose)))>0.000001:
            new_camera_pose = camera_nodes[0].matrix
        else:
            new_camera_pose = camera_nodes[1].matrix
    else:
        print(camera_nodes)
        new_camera_pose = camera_nodes[0].matrix
    formatted_new_camera_pose = np.array2string(new_camera_pose, separator=', ',
                                                formatter={'float_kind': lambda x: f"{x:.6f}"})
    print("Chosen camera pose Matrix:")
    print(formatted_new_camera_pose)

    # choose the light intensity from the viewer
    new_light_intensity=args.light_intensity
    count=0
    while True:
        intensity_input = input("Enter new light intensity number (>0) or 'q' to quit: ")
        if intensity_input.lower() == 'q':
            break
        try:
            count=count+1
            # Update light intensity
            new_light_intensity = float(intensity_input)
            light.intensity = new_light_intensity
            # Re-render the scene
            viewer.render_lock.acquire()
            scene.set_pose(light_node, pose=new_camera_pose)
            viewer.render_lock.release()
        except ValueError:
            print("Invalid input. Please enter a valid number or 'q' to quit.")
    if count==0:
        new_light_intensity=args.light_intensity
    print("Chosen light intensity:")
    print(new_light_intensity)

    # close the viewer
    viewer.close_external()
    del viewer
    return new_camera_pose,new_light_intensity

def change_saturation(image, factor):
    hsv_image = rgb2hsv(image)
    hsv_image[..., 1] *= factor
    hsv_image[..., 1] = np.clip(hsv_image[..., 1], 0, 1)
    rgb_image = hsv2rgb(hsv_image) * 255
    rgb_image = np.clip(rgb_image, 0, 255).astype(np.uint8)
    return rgb_image

def generate_gif(new_camera_pose,new_light_intensity,args):
    # initialize scene
    scene, mesh_node = init_scene(args)
    # Set up the camera
    camera = pyrender.PerspectiveCamera(yfov=np.pi / 3.0)
    scene.add(camera, pose=new_camera_pose)
    # Set up the light
    light = pyrender.DirectionalLight(color=np.ones(3), intensity=new_light_intensity)
    scene.add(light, pose=new_camera_pose)

    # make directory to save frames
    os.makedirs(args.frames_folder_path, exist_ok=True)
    # render the scene from different angles
    r = pyrender.OffscreenRenderer(args.image_width, args.image_height)
    angle_step = 360 / args.num_frames
    for i in range(args.num_frames):
        # rotate the model clockwise
        angle = np.radians(-i * angle_step)
        rotation_matrix = np.array([
            [np.cos(angle), 0, np.sin(angle), 0],
            [0, 1, 0, 0],
            [-np.sin(angle), 0, np.cos(angle), 0],
            [0, 0, 0, 1]
        ])
        mesh_pose = np.dot(rotation_matrix, np.eye(4))
        scene.set_pose(mesh_node, pose=mesh_pose)
        # render
        color, depth = r.render(scene)
        color = change_saturation(color, args.image_saturation)
        # save the rendered frame
        frame_path = os.path.join(args.frames_folder_path, f'frame_{i:03d}.png')
        imageio.imwrite(frame_path, color)

    # create a GIF from the rendered frames
    frames = []
    for i in range(args.num_frames):
        frame_path = os.path.join(args.frames_folder_path, f'frame_{i:03d}.png')
        frames.append(imageio.imread(frame_path))
    imageio.mimsave(args.gif_path, frames, duration=args.image_duration, loop=args.image_loops)
    print(f"GIF saved to {args.gif_path}")


if __name__ == "__main__":
    args = init_args()
    new_camera_pose,new_light_intensity=change_parameters(args)
    generate_gif(new_camera_pose,new_light_intensity,args)






