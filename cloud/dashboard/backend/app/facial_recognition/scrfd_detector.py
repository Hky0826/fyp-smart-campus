import os
import cv2
import numpy as np
import onnxruntime as ort

class SCRFDDetector:
    def __init__(self, model_path: str, input_size=(640, 640), conf_thresh=0.5, nms_thresh=0.4):
        self.model_path = model_path
        self.input_size = input_size
        self.conf_thresh = conf_thresh
        self.nms_thresh = nms_thresh
        self.session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
        
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        
        # Grid/anchor generation parameters
        self._feat_stride_fpn = [8, 16, 32]
        self._num_anchors = 2
        self.anchor_centers = {}
        self._init_anchors()

    def _init_anchors(self):
        for stride in self._feat_stride_fpn:
            f_h = self.input_size[0] // stride
            f_w = self.input_size[1] // stride
            
            # Generate grid centers
            grid_y, grid_x = np.mgrid[0:f_h, 0:f_w]
            centers = np.stack((grid_x, grid_y), axis=-1).astype(np.float32)
            centers = (centers * stride).reshape((-1, 2))
            
            # Since there are 2 anchors per cell, duplicate each center
            centers = np.stack([centers] * self._num_anchors, axis=1).reshape((-1, 2))
            self.anchor_centers[stride] = centers

    def detect(self, img: np.ndarray):
        # Preprocess: resize to input_size (640x640) and normalize
        h, w = img.shape[:2]
        scale_x = w / self.input_size[1]
        scale_y = h / self.input_size[0]
        
        blob = cv2.resize(img, self.input_size, interpolation=cv2.INTER_LINEAR)
        blob = blob.astype(np.float32)
        # Normalize: (blob - 127.5) / 128.0 (InsightFace standard)
        blob = (blob - 127.5) / 128.0
        blob = np.transpose(blob, (2, 0, 1))
        blob = np.expand_dims(blob, axis=0)
        
        # Run inference
        outputs = self.session.run(self.output_names, {self.input_name: blob})
        
        # The output order is typically:
        # 0: score_8, 1: score_16, 2: score_32 (or similar)
        # We can map them based on their row counts (12800, 3200, 800)
        scores_list = []
        bboxes_list = []
        kpss_list = []
        
        # Map outputs by shape
        for out in outputs:
            shape = out.shape
            # If shape is [1, N, C] or [N, C]
            if len(shape) == 3:
                out = out[0]
            
            N, C = out.shape
            if C == 1:
                scores_list.append((N, out))
            elif C == 4:
                bboxes_list.append((N, out))
            elif C == 10:
                kpss_list.append((N, out))
                
        # Sort them by N (12800, 3200, 800)
        scores_list.sort(key=lambda x: x[0], reverse=True)
        bboxes_list.sort(key=lambda x: x[0], reverse=True)
        kpss_list.sort(key=lambda x: x[0], reverse=True)
        
        proposals = []
        confidences = []
        landmarks_list = []
        
        for idx, stride in enumerate(self._feat_stride_fpn):
            scores = scores_list[idx][1][:, 0]
            bbox_preds = bboxes_list[idx][1]
            kps_preds = kpss_list[idx][1]
            centers = self.anchor_centers[stride]
            
            # Find indices above threshold
            inds = np.where(scores >= self.conf_thresh)[0]
            for ind in inds:
                score = scores[ind]
                cx, cy = centers[ind]
                
                # Decode bbox: left, top, right, bottom relative to center
                l, t, r, b = bbox_preds[ind] * stride
                x1 = cx - l
                y1 = cy - t
                x2 = cx + r
                y2 = cy + b
                
                # Rescale to original size
                x1 *= scale_x
                y1 *= scale_y
                x2 *= scale_x
                y2 *= scale_y
                
                proposals.append([x1, y1, x2, y2])
                confidences.append(float(score))
                
                # Decode keypoints
                kps = kps_preds[ind].reshape((5, 2)) * stride
                kps[:, 0] = (centers[ind, 0] + kps_preds[ind].reshape((5, 2))[:, 0] * stride) # wait!
                # Let's decode properly:
                # InsightFace SCRFD keypoint predictions are offsets relative to the anchor center
                kps_decoded = np.zeros((5, 2), dtype=np.float32)
                for k in range(5):
                    kps_decoded[k, 0] = (cx + kps_preds[ind, k*2] * stride) * scale_x
                    kps_decoded[k, 1] = (cy + kps_preds[ind, k*2+1] * stride) * scale_y
                landmarks_list.append(kps_decoded)
                
        if len(proposals) == 0:
            return []
            
        # Non-Maximum Suppression (NMS)
        boxes = np.array(proposals, dtype=np.float32)
        scores = np.array(confidences, dtype=np.float32)
        
        # Calculate box areas
        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]
        areas = (x2 - x1) * (y2 - y1)
        
        order = scores.argsort()[::-1]
        keep = []
        
        while order.size > 0:
            i = order[0]
            keep.append(i)
            
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            
            w_int = np.maximum(0.0, xx2 - xx1)
            h_int = np.maximum(0.0, yy2 - yy1)
            inter = w_int * h_int
            
            iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-8)
            inds = np.where(iou <= self.nms_thresh)[0]
            order = order[inds + 1]
            
        results = []
        for idx in keep:
            results.append({
                "bbox": proposals[idx],
                "confidence": confidences[idx],
                "landmarks": landmarks_list[idx]
            })
        return results
