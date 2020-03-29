"""
detector
Copyright (c) 2020 Nathan Cueto
Licensed under the MIT License (see LICENSE for details)
Written by Nathan Cueto
"""

import os
import sys
import json
# import datetime # not really useful so remove soon pls
import numpy as np
import skimage.draw
import imgaug # should augment this improt as well haha
# from PIL import Image

# Root directory of project
ROOT_DIR = os.path.abspath("../../")

# Import Mask RCNN
sys.path.append(ROOT_DIR)  # To find local version of the library
sys.path.append(os.path.join(os.path.abspath('.'), 'TecoGAN/'))
from mrcnn.config import Config
from mrcnn import model as modellib, utils
# sys.path.insert(1, 'samples/hentai/')
# from hentai import HentaiConfig
from cv2 import VideoCapture, CAP_PROP_FRAME_HEIGHT, CAP_PROP_FRAME_WIDTH, CAP_PROP_FPS, VideoWriter, VideoWriter_fourcc, resize, INTER_LANCZOS4, INTER_AREA, GaussianBlur, filter2D, bilateralFilter, blur
# from TecoGAN import *
import TecoGAN.main

DEFAULT_LOGS_DIR = os.path.join(ROOT_DIR, "logs")

# Path to trained weights
WEIGHTS_PATH = os.path.join(ROOT_DIR, "weights.h5")

# taking this from hentai to avoid import
class HentaiConfig(Config):
    """Configuration for training on the toy  dataset.
    Derives from the base Config class and overrides some values.
    """
    # Give the configuration a recognizable name
    NAME = "hentai"

    # We use a GPU with 12GB memory, which can fit two images.
    # Adjust down if you use a smaller GPU.
    IMAGES_PER_GPU = 1

    # Number of classes (including background)
    NUM_CLASSES = 1 + 1 + 1 # Background + censor bar + mosaic

    # Number of training steps per epoch, equal to dataset train size
    STEPS_PER_EPOCH = 1490

    # Skip detections with < 75% confidence NOTE: lowered this because its better for false positives
    DETECTION_MIN_CONFIDENCE = 0.75

class Detector():
    # at startup, dont create model yet
    def __init__(self, weights_path):
        class InferenceConfig(HentaiConfig):
            # Set batch size to 1 since we'll be running inference on
            # one image at a time. Batch size = GPU_COUNT * IMAGES_PER_GPU
            GPU_COUNT = 1
            IMAGES_PER_GPU = 1
        self.config = InferenceConfig()

        self.weights_path = weights_path
        # counts how many non-png images, if >1 then warn user
        self.dcp_compat = 0
        try:
            self.out_path = os.path.join(os.path.abspath('.'), "TG_temp/TG_out/")
            self.out2_path = os.path.join(os.path.abspath('.'), "TG_temp/TG_out2/")
            self.temp_path = os.path.join(os.path.abspath('.'), "TG_temp/temp/")
            self.temp_path2 = os.path.join(os.path.abspath('.'), "TG_temp/temp2/")
            self.fin_path = os.path.join(os.path.abspath('.'), "TG_output/")
        except:
            print("ERROR in Detector init: Cannot find TG_out or some dir within.")
            return
        self.flags = TecoGAN.main.setFLAGS(output_dir=self.out_path, input_dir_LR=self.temp_path, output_dir2=self.out2_path, input_dir_LR2=self.temp_path2) #NOTE: Change this as needed
        # keep model loading to be done later, not now

    # Clean out temp working images from all directories in TG_temp. Code from https://stackoverflow.com/questions/185936/how-to-delete-the-contents-of-a-folder
    def clean_work_dirs(self):
        folders = [self.out_path, self.out2_path, self.temp_path, self.temp_path2]
        for folder in folders:
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    print('Failed to delete %s. Reason: %s' % (file_path, e))

    # Make sure this is called before using model weights
    def load_weights(self):
        print('Loading weights...', end='  ')
        try:
            self.model = modellib.MaskRCNN(mode="inference", config=self.config,
                                        model_dir=DEFAULT_LOGS_DIR)
            self.model.load_weights(self.weights_path, by_name=True)
            print("Weights loaded")
        except Exception as e:
            print("ERROR in load_weights: Model Load. Ensure you have your weights.h5 file!", end=' ')
            print(e)

    def apply_cover(self, image, mask):
        """Apply cover over image. Based off of Mask-RCNN Balloon color splash function
        image: RGB image [height, width, 3]
        mask: instance segmentation mask [height, width, instance count]
        Returns result covered image.
        """
        # Copy color pixels from the original color image where mask is set
        # green = np.array([[[0, 255, 0]]], dtype=np.uint8)
        # print('apply_cover: shape of image is',image.shape)
        green = np.zeros([image.shape[0], image.shape[1], image.shape[2]], dtype=np.uint8)
        green[:,:] = [0, 255, 0]
        if mask.shape[-1] > 0:
            # We're treating all instances as one, so collapse the mask into one layer
            mask = (np.sum(mask, -1, keepdims=True) < 1)
            cover = np.where(mask, image, green).astype(np.uint8)
        else:
            # error case, return image
            cover = image
        return cover, mask

    def splice(self, image, mask, gan_out):
        if mask.shape[-1] > 0:
            mask = (np.sum(mask, -1, keepdims=True) < 1)
            cover = np.where(mask, image, gan_out).astype(np.uint8)
        else:
            #error case, return image
            cover=image
        return cover

    # return number of jpgs that were not processed
    def get_non_png(self):
        return self.dcp_compat        

    # Runs hent-AI detection, and TGAN on image.
    def TGAN(self, img_path, img_name, is_video=False):
        
        # First, run detection on image
        # Image read
        if is_video == False:
            try:
                image = skimage.io.imread(img_path) # problems with strange shapes
                if image.ndim != 3: 
                    image = skimage.color.gray2rgb(image) # convert to rgb if greyscale
                if image.shape[-1] == 4:
                    image = image[..., :3] # strip alpha channel
            except Exception as e:
                print("ERROR in TGAN: Image read. Skipping. image_path=", img_path)
                print(e)
                return
            r = self.model.detect([image], verbose=0)[0] 
            remove_indices = np.where(r['class_ids'] != 2) # remove bars: class 2
            new_masks = np.delete(r['masks'], remove_indices, axis=2)

            # Now we have the mask from detection, begin TGAN by first resizing img into temp folder. 
            try:
                mini_img = resize(image, (int(image.shape[1]/16), int(image.shape[0]/16)), interpolation=INTER_AREA) # downscale to 1/16
                mini_blur = bilateralFilter(mini_img, 3, 70, 70)
                # mini_blur = GaussianBlur(mini_img, (3,3), 0)
                # sharp_low = -.75
                # sharp_point = 4 # default sharpening values from my screentone remover
                # s_kernel = np.array([[0, sharp_low, 0], [sharp_low, sharp_point, sharp_low], [0, sharp_low, 0]]) # filter convolution applies sharpening
                # sharpened = filter2D(mini_blur, -1, s_kernel)
                # bil2 = bilateralFilter(sharpened, 3, 70, 70)
                file_name = self.temp_path + img_name[:-4] + '.png' # need to save a sequence of pngs for TGAN operation
                skimage.io.imsave(file_name, mini_blur)
            except:
                print("ERROR in TGAN: resize. Skipping. image_path=",img_path)
                return
            # Double tecoGAN runs to super resolute by 16x
            TecoGAN.main.TGAN_inference(self.flags) 
            # blur the middle image using code from MY screentone remover
            gan1_out = skimage.io.imread(self.out_path + img_name[:-4] + '.png')
            # gan_blurred = GaussianBlur(gan1_out, (3,3), 0) 
            
            # sharp_low = -1
            # sharp_point = 9.0 # default sharpening values from my screentone remover
            # s_kernel = np.array([[-1, sharp_low, -1], [sharp_low, sharp_point, sharp_low], [-1, sharp_low, -1]]) # filter convolution applies sharpening
            # sharpened = filter2D(gan1_out, -1, s_kernel)
            bi_blur = bilateralFilter(gan1_out, 5, 70, 70) #apply two blur types

            skimage.io.imsave(self.temp_path2 + img_name[:-4] + '.png', bi_blur) #save to temp2 path
            TecoGAN.main.TGAN_inference(self.flags, second=True)
            # resize again, from out_path to to temp_path2
            # half_image = skimage.io.imread(os.path.join(out_path, img_name))
            # mini_img2 = resize(half_image, (int(image.shape[1]/4), int(image.shape[0]/4)), interpolation=INTER_NEAREST)
            # file_name = temp_path2 + img_name[:-4] + '.png' # need to save a sequence of pngs for TGAN operation
            # skimage.io.imsave(file_name, mini_img2)
            # Image splice the detected region over the source image
            gan_img_path = self.out2_path + img_name[:-4] + '.png' # will be forced to png in tgan
            gan_image = skimage.io.imread(gan_img_path)
            fin_img = self.splice(image, new_masks, gan_image)

            # try:
            # Save output, now force save as png
            file_name = self.fin_path + img_name[:-4] + '.png'
            skimage.io.imsave(file_name, fin_img)
            print("Splice complete. Cleaning work directories...")
            self.clean_work_dirs()
            # except:
            #     print("ERROR in TGAN: Image write. Skipping. image_path=", img_path)


    # TGAN folder running function
    def run_TGAN(self, in_path = None, is_video = False, force_jpg = False):
        assert in_path

        # similar to run_on_folder
        img_list = []
        for file in os.listdir(in_path):
            # TODO: check what other filetpyes supported
            try:
                if file.endswith('.png') or file.endswith('.PNG') or file.endswith(".jpg") or file.endswith(".JPG") or file.endswith(".mp4"):
                    img_list.append((in_path + '/' + file, file))
            except:
                print("ERROR in run_TGAN: File parsing. file=", file)
        # begin TGAN on every image
        file_counter=0
        for img_path, img_name in img_list:
            self.TGAN(img_path=img_path, img_name=img_name, is_video=is_video)
            print('TGAN on image', file_counter, 'is complete')
            file_counter += 1

    def video_create(self, image_path=None, dcp_path=''):
        assert image_path
        
        # Video capture to get shapes and stats
        # Only supports 1 video at a time, but this can still get mp4 only
        
        vid_list = []
        for file in os.listdir(image_path):
            if len(vid_list) == 1:
                print("WARNING: More than 1 video in input directory! Assuming you want the first video.")
                break
            if file.endswith('mp4') or file.endswith('MP4'):
                vid_list.append(image_path + '/' + file)
            
        
        video_path = vid_list[0] # ONLY works with 1 video for now
        vcapture = VideoCapture(video_path)
        width = int(vcapture.get(CAP_PROP_FRAME_WIDTH))
        height = int(vcapture.get(CAP_PROP_FRAME_HEIGHT))
        fps = vcapture.get(CAP_PROP_FPS)

        # Define codec and create video writer, video output is purely for debugging and educational purpose. Not used in decensoring.
        file_name = str(file) + '_uncensored.avi'
        vwriter = VideoWriter(file_name,
                                    VideoWriter_fourcc(*'MJPG'),
                                    fps, (width, height))
        count = 0
        print("Beginning build. Do ensure only relevant images are in source directory")
        input_path = dcp_path + '/decensor_output/'
        img_list = []
        # output of the video detection should be in order anyway
        # os.chdir(input_path)
        # files = filter(os.path.isfile, os.listdir(input_path))
        # files = [os.path.join( f) for f in files]    
        # files.sort(key=lambda x: os.path.getmtime(x))
        # for file in files:
        for file in os.listdir(input_path):
            # TODO: check what other filetpyes supported
            if file.endswith('.png') or file.endswith('.PNG'):
                img_list.append(input_path  + file)
                # print('adding image ', input_path  + file)
        for img in img_list:
            print("frame: ", count)
            # Read next image
            image = skimage.io.imread(img) # Should be no alpha channel in created image
            # Add image to video writer, after flipping R and B value
            image = image[..., ::-1]
            vwriter.write(image)
            count += 1

        vwriter.release()
        print('video complete')

    # save path and orig video folder are both paths, but orig video folder is for original mosaics to be saved.
    # fname = filename.
    # image_path = path of input file, image or video
    def detect_and_cover(self, image_path=None, fname=None, save_path='', is_video=False, orig_video_folder=None, force_jpg=False, is_mosaic=False):
        assert image_path
        assert fname # replace these with something better?
        
        if is_video: # TODO: video capabilities will finalize later
            # from cv2 import VideoCapture, CAP_PROP_FRAME_HEIGHT, CAP_PROP_FRAME_WIDTH, CAP_PROP_FPS, VideoWriter, VideoWriter_fourcc
            
            # Video capture
            video_path = image_path
            vcapture = VideoCapture(video_path)
            width = int(vcapture.get(CAP_PROP_FRAME_WIDTH))
            height = int(vcapture.get(CAP_PROP_FRAME_HEIGHT))
            fps = vcapture.get(CAP_PROP_FPS)
    
            # Define codec and create video writer, video output is purely for debugging and educational purpose. Not used in decensoring.
            file_name = fname + "_with_censor_masks.avi"
            vwriter = VideoWriter(file_name,
                                      VideoWriter_fourcc(*'MJPG'),
                                      fps, (width, height))
            count = 0
            success = True
            print("Video read complete, starting video detection:")
            while success:
                print("frame: ", count)
                # Read next image
                success, image = vcapture.read()
                if success:
                    # OpenCV returns images as BGR, convert to RGB
                    image = image[..., ::-1]
                    # save frame into decensor input original. Need to keep names persistent.
                    im_name = fname[:-4] # if we get this far, we definitely have a .mp4. Remove that, add count and .png ending
                    file_name = orig_video_folder + im_name + str(count).zfill(6) + '.png' # NOTE Should be adequite for having 10^6 frames, which is more than enough for even 30 mintues total.
                    # print('saving frame as ', file_name)
                    skimage.io.imsave(file_name, image)
                    
                    # Detect objects
                    r = self.model.detect([image], verbose=0)[0]

                    # Remove unwanted class, code from https://github.com/matterport/Mask_RCNN/issues/1666
                    remove_indices = np.where(r['class_ids'] != 2) # remove bars: class 1
                    # new_class_ids = np.delete(r['class_ids'], indices_to_remove, axis=0)
                    # new_rois = np.delete(r['rois'], indices_to_remove, axis=0)
                    # new_scores = np.delete(r['scores'], indices_to_remove, axis=0)
                    new_masks = np.delete(r['masks'], remove_indices, axis=2)

                    # Apply cover
                    cov, mask = self.apply_cover(image, new_masks)
                    
                    # save covered frame into input for decensoring path
                    file_name = save_path + im_name + str(count).zfill(6) + '.png'
                    # print('saving covered frame as ', file_name)
                    skimage.io.imsave(file_name, cov)

                    # RGB -> BGR to save image to video
                    cov = cov[..., ::-1]
                    # Add image to video writer
                    vwriter.write(cov)
                    count += 1

            vwriter.release()
            print('video complete')
        else:
            # print("Running on ", end='')
            # print(image_path)
            # Read image
            try:
                image = skimage.io.imread(image_path) # problems with strange shapes
                if image.ndim != 3: 
                    image = skimage.color.gray2rgb(image) # convert to rgb if greyscale
                if image.shape[-1] == 4:
                    image = image[..., :3] # strip alpha channel
            except:
                print("ERROR in detect_and_cover: Image read. Skipping. image_path=", image_path)
                return
            # Detect objects
            # try:
            r = self.model.detect([image], verbose=0)[0]
            # Remove unwanted class, code from https://github.com/matterport/Mask_RCNN/issues/1666
            if is_mosaic==True or is_video==True:
                remove_indices = np.where(r['class_ids'] != 2) # remove bars: class 2
            else:
                remove_indices = np.where(r['class_ids'] != 1) # remove mosaic: class 1
            # new_class_ids = np.delete(r['class_ids'], indices_to_remove, axis=0)
            # new_rois = np.delete(r['rois'], indices_to_remove, axis=0)
            # new_scores = np.delete(r['scores'], indices_to_remove, axis=0)
            new_masks = np.delete(r['masks'], remove_indices, axis=2)
            # except:
            #     print("ERROR in detect_and_cover: Model detect")
            
            cov, mask = self.apply_cover(image, new_masks)
            try:
                # Save output, now force save as png
                file_name = save_path + fname[:-4] + '.png'
                skimage.io.imsave(file_name, cov)
            except:
                print("ERROR in detect_and_cover: Image write. Skipping. image_path=", image_path)
            # print("Saved to ", file_name)

    # Function for file parsing, calls the aboven detect_and_cover
    def run_on_folder(self, input_folder, output_folder, is_video=False, orig_video_folder=None, force_jpg=False, is_mosaic=False):
        assert input_folder
        assert output_folder # replace with catches and popups

        if force_jpg==True:
            print("WARNING: force_jpg=True. jpg support is not guaranteed, beware.")

        file_counter = 0
        if(is_video == True):
            # support for multiple videos if your computer can even handle that
            vid_list = []
            for file in os.listdir(input_folder):
                if file.endswith('mp4') or file.endswith('MP4'):
                    vid_list.append((input_folder + '/' + file, file))
            
            for vid_path, vid_name in vid_list:
                # video will not support separate mask saves
                self.detect_and_cover(vid_path, vid_name, output_folder, is_video=True, orig_video_folder=orig_video_folder)
                print('detection on video', file_counter, 'is complete')
                file_counter += 1
        else:
            # obtain inputs from the input folder
            img_list = []
            for file in os.listdir(input_folder):
                # TODO: check what other filetpyes supported
                try:
                    if force_jpg == False:
                        if file.endswith('.png') or file.endswith('.PNG'):
                            img_list.append((input_folder + '/' + file, file))
                        elif file.endswith(".jpg") or file.endswith(".JPG"):
                            # img_list.append((input_folder + '/' + file, file)) # Do not add jpgs. Conversion to png must happen first
                            self.dcp_compat += 1
                    else:
                        if file.endswith('.png') or file.endswith('.PNG') or file.endswith(".jpg") or file.endswith(".JPG"):
                            img_list.append((input_folder + '/' + file, file))
                except:
                    print("ERROR in run_on_folder: File parsing. file=", file)
            

            # save run detection with outputs to output folder
            for img_path, img_name in img_list:
                self.detect_and_cover(img_path, img_name, output_folder, force_jpg=force_jpg, is_mosaic=is_mosaic)  #sending force_jpg for debugging
                print('Detection on image', file_counter, 'is complete')
                file_counter += 1



# main only used for debugging here. Comment out pls
if __name__ == '__main__':
    import argparse
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Utilize Mask R-CNN to detect censor bars.')
    parser.add_argument('--weights', required=True,
                        metavar="/path/to/weights.h5",
                        help="Path to weights.h5")
    parser.add_argument('--imagedir', required=True,
                        metavar="path to image folder",
                        help='Folder of images to apply mask coverage on')
    # parser.add_argument('--video', required=False,
    #                     metavar="path or URL to video",
    #                     help='Video to apply effect on')
    args = parser.parse_args()
    weights_path = args.weights
    images_path = args.imagedir
    output_dir = "temp_out/"
    print('Initializing Detector class')
    detect_instance = Detector(weights_path=args.weights)
    print('loading weights')
    detect_instance.load_weights()
    print('running TGAN on in and out folder')
    # detect_instance.run_on_folder(input_folder=images_path, output_folder=output_dir)
    detect_instance.run_TGAN(in_path=images_path)
    print("Fin")
    