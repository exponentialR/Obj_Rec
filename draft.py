import argparse
import os
import sys
from pathlib import Path
import cv2
import torch
import torch.backends.cudnn as cudnn

FILE = Path(__file__).resolve()
ROOT = FILE.parents[0]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
ROOT = Path(os.path.relpath(ROOT, Path.cwd()))
from models.common import DetectMultiBackend  # To get the following imports working, clone the repository
from utils.datasets import IMG_FORMATS, VID_FORMATS, LoadImages, LoadStreams
from utils.general import (LOGGER, check_file, check_img_size, check_imshow, check_requirements, colorstr,
                           increment_path, non_max_suppression, print_args, scale_coords, strip_optimizer, xyxy2xywh)
from utils.plots import Annotator, colors, save_one_box
from utils.torch_utils import select_device, time_sync


# inference size (height, width)


@torch.no_grad()
def run(source: int, weights: object = ROOT / 'best.pt',  # model.pt path(s)
        imgsz: object = (640, 640),
        conf_thres: object = 0.25,  # confidence threshold
        iou_thres: object = 0.45,  # NMS IOU threshold
        max_det: object = 1000,  # maximum detections per image
        device: object = 'cpu',  # cuda device, i.e. 0 or 0,1,2,3 or cpu
        view_img: object = False,  # show results
        save_txt: object = False,  # save results to *.txt
        save_conf: object = False,  # save confidences in --save-txt labels
        save_crop: object = False,  # save cropped prediction boxes
        nosave: object = False,  # do not save images/videos
        classes: object = None,  # filter by class: --class 0, or --class 0 2 3
        agnostic_nms: object = False,  # class-agnostic NMS
        augment: object = False,  # augmented inference
        visualize: object = False,  # visualize features
        update: object = False,  # update all models
        project: object = ROOT / 'runs/detect',  # save results to project/name
        name: object = 'exp',  # save results to project/name
        exist_ok: object = False,  # existing project/name ok, do not increment
        line_thickness: object = 3,  # bounding box thickness (pixels)
        hide_labels: object = False,  # hide labels
        hide_conf: object = False,  # hide confidences
        half: object = False,  # use FP16 half-precision inference
        dnn: object = False) -> object:
    # source = str(source)
    webcam = source.isnumeric()
    if not webcam:
        print('Source is not a Stream')
    else:
        save_dir = increment_path(Path(project) / name, exist_ok=exist_ok)  # increment run
        (save_dir / 'labels' if save_txt else save_dir).mkdir(parents=True, exist_ok=True)  # make dir

        device = select_device(device)
        model = DetectMultiBackend(weights, device=device, dnn=dnn)
        stride, names, pt, jit, onnx, engine = model.stride, model.names, model.pt, model.jit, model.onnx, model.engine
        imgsz = check_img_size(imgsz, s=stride)  # check image size

        # Half
        half &= (pt or jit or engine) and device.type != 'cpu'  # half precision only supported by PyTorch on CUDA
        if pt or jit:
            model.model.half() if half else model.model.float()
        view_img = check_imshow()
        cudnn.benchmark = True  # set True to speed up constant image size inference
        dataset = LoadStreams(source, img_size=imgsz, stride=stride, auto=pt)
        bs = len(dataset)  # batch_size
        vid_path, vid_writer = [None] * bs, [None] * bs

        model.warmup(imgsz=(1, 3, *imgsz), half=half)
        dt, seen = [0.0, 0.0, 0.0], 0
        for path, im, im0s, vid_cap, s in dataset:
            t1 = time_sync()
            im = torch.from_numpy(im).to(device)
            im = im.half() if half else im.float()
            im /= 255  # convert input image to float
            if len(im.shape) == 3:
                im = im[None]
            t2 = time_sync()
            dt[0] += t2 - t1

            # peforming inference
            visualize = increment_path(save_dir / Path(path).stem, mkdir=True) if visualize else False
            pred = model(im, augment=augment, visualize=visualize)
            t3 = time_sync()
            dt[1] += t3 - t2

            pred = non_max_suppression(pred, conf_thres, iou_thres, classes, agnostic_nms, max_det=max_det)
            dt[2] += time_sync() - t3

            # Process prediction
            for i, det in enumerate(pred):
                seen += 1
                p, im0, frame = path[i], im0s[i].copy(), dataset.count
                s += f'{i}: '
                p = Path(p)
                save_path = str(save_dir / p.name)
                txt_path = str(save_dir / 'labels' / p.stem) + (
                    '' if dataset.mode == 'image' else f'_{frame}')  # im.txt
                s += '%gx%g ' % im.shape[2:]
                gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]
                imc = im0.copy() if save_crop else im0
                annotator = Annotator(im0, line_width=line_thickness, example=str(names))
                if len(det):
                    # Rescale boxes from img_size to im0 size
                    det[:, :4] = scale_coords(im.shape[2:], det[:, :4], im0.shape).round()

                    # Print results
                    for c in det[:, -1].unique():
                        n = (det[:, -1] == c).sum()  # detections per class
                        s += f"{n} {names[int(c)]}{'s' * (n > 1)}, "  # add to string

                    # Write results
                    # for *xyxy, conf, cls in reversed(det):
                    #         if save_txt:  # Write to file
                    #                 xywh = (xyxy2xywh(torch.tensor(xyxy).view(1, 4)) / gn).view(
                    #                         -1).tolist()  # normalized xywh
                    #                 line = (cls, *xywh, conf) if save_conf else (cls, *xywh)  # label format
                    #                 with open(txt_path + '.txt', 'a') as f:
                    #                         f.write(('%g ' * len(line)).rstrip() % line + '\n')
                    #
                    #         if save_img or save_crop or view_img:  # Add bbox to image
                    #                 c = int(cls)  # integer class
                    #                 label = None if hide_labels else (
                    #                         names[c] if hide_conf else f'{names[c]} {conf:.2f}')
                    #                 annotator.box_label(xyxy, label, color=colors(c, True))
                    #                 if save_crop:
                    #                         save_one_box(xyxy, imc, file=save_dir / 'crops' / names[
                    #                                 c] / f'{p.stem}.jpg', BGR=True)

                    # Print time (inference-only)
                LOGGER.info(f'{s}Done. ({t3 - t2:.3f}s)')

                im0 = annotator.result()
                if view_img:
                    cv2.imshow(str(p), im0)
                    cv2.waitKey(1)  # 1 millisecond

        # t = tuple(x / seen * 1E3 for x in dt)  # speeds per image
        # LOGGER.info(f'Speed: %.1fms pre-process, %.1fms inference, %.1fms NMS per image at shape {(1, 3, *imgsz)}' % t)
        # if save_txt or save_img:
        #         s = f"\n{len(list(save_dir.glob('labels/*.txt')))} labels saved to {save_dir / 'labels'}" if save_txt else ''
        #         LOGGER.info(f"Results saved to {colorstr('bold', save_dir)}{s}")
        if update:
            strip_optimizer(weights)


def main():
    inference_type = 0
    run(inference_type)


if __name__ == "__main__":
    main()
