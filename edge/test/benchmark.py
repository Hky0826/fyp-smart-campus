import argparse
import collections
import json
import logging
import statistics
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import psutil

# Add project root to sys.path so we can import edge modules
import sys
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from edge.facial_recognition.src.config import AccessControlConfig
from edge.facial_recognition.src.face.database import DeviceUserRepository
from edge.facial_recognition.src.face.detection import HailoSCRFDDetector
from edge.facial_recognition.src.face.embedding import HailoArcFaceEmbedder
from edge.facial_recognition.src.pipelines.access_control import AccessControlPipeline


logger = logging.getLogger(__name__)


class StreamQueue:
    def __init__(self, maxlen: int):
        self.q = collections.deque(maxlen=maxlen)
        self.lock = threading.Lock()
        self.dropped_frames = 0
        self.produced_frames = 0
        self.max_depth = 0

    def put(self, item: Tuple[np.ndarray, float]) -> None:
        with self.lock:
            self.produced_frames += 1
            if len(self.q) == self.q.maxlen:
                self.dropped_frames += 1
            self.q.append(item)
            if len(self.q) > self.max_depth:
                self.max_depth = len(self.q)

    def get(self) -> Optional[Tuple[np.ndarray, float]]:
        with self.lock:
            if not self.q:
                return None
            return self.q.popleft()


def video_producer(
    stream_id: int,
    video_path: str,
    queue: StreamQueue,
    target_fps: float,
    end_event: threading.Event,
    mode: str,
) -> None:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Stream {stream_id}: Cannot open video {video_path}")
        return

    frames = []
    if mode == "predecoded":
        logger.info(f"Stream {stream_id}: Pre-decoding video frames...")
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            # Pre-resize to 640x480 to mimic camera input if needed, or leave as is
            frames.append(frame)
        cap.release()
        if not frames:
            logger.error(f"Stream {stream_id}: No frames decoded.")
            return
        
        frame_idx = 0
        while not end_event.is_set():
            start_t = time.perf_counter()
            frame = frames[frame_idx % len(frames)]
            queue.put((frame, time.perf_counter()))
            frame_idx += 1
            
            elapsed = time.perf_counter() - start_t
            sleep_t = (1.0 / target_fps) - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)
    else:
        while not end_event.is_set():
            start_t = time.perf_counter()
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
            if ret:
                queue.put((frame, time.perf_counter()))
            
            elapsed = time.perf_counter() - start_t
            sleep_t = (1.0 / target_fps) - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)
        cap.release()


def system_monitor(end_event: threading.Event, metrics: Dict[str, List[float]]) -> None:
    while not end_event.is_set():
        cpu = psutil.cpu_percent(interval=1.0)
        ram = psutil.virtual_memory().percent
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp = float(f.read()) / 1000.0
        except Exception:
            temp = 0.0
        
        metrics["cpu"].append(cpu)
        metrics["ram"].append(ram)
        metrics["temp"].append(temp)


def calculate_percentiles(data: List[float]) -> Dict[str, float]:
    if not data:
        return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "avg": 0.0}
    s = sorted(data)
    n = len(s)
    return {
        "p50": s[int(n * 0.50)] if n > 0 else 0.0,
        "p90": s[int(n * 0.90)] if n > 0 else 0.0,
        "p95": s[int(n * 0.95)] if n > 0 else 0.0,
        "p99": s[int(n * 0.99)] if n > 0 else 0.0,
        "avg": statistics.mean(s)
    }


def main():
    parser = argparse.ArgumentParser(description="Multi-stream Pipeline Benchmark")
    parser.add_argument("--streams", type=int, choices=[1, 2, 3, 4], default=1, help="Number of concurrent streams")
    parser.add_argument("--video", type=str, default="test_video.mp4", help="Video file to use as input source")
    parser.add_argument("--mode", choices=["end-to-end", "predecoded"], default="end-to-end")
    parser.add_argument("--fps", type=float, default=10.0, help="Target request rate (FPS) per stream")
    parser.add_argument("--duration", type=int, default=30, help="Benchmark duration in seconds")
    parser.add_argument("--stale-ms", type=float, default=100.0, help="Threshold for stale frames in ms")
    parser.add_argument("--queue-size", type=int, default=2, help="Bounded queue size per stream")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger.info(f"Starting benchmark: {args.streams} streams, Mode: {args.mode}, Target FPS: {args.fps}")

    config = AccessControlConfig()
    logger.info("Loading Hailo models...")
    detector = HailoSCRFDDetector(
        config.detector_model_path,
        confidence_threshold=config.detection_threshold,
        log_empty_detections=False,
    )
    embedder = HailoArcFaceEmbedder(config.embedding_model_path)
    repository = DeviceUserRepository(config.database_path)

    # Pre-warm
    logger.info("Pre-warming Hailo models...")
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detector.detect(dummy_frame)

    streams = []
    end_event = threading.Event()

    for i in range(args.streams):
        pipeline = AccessControlPipeline(detector, embedder, repository, config=config)
        queue = StreamQueue(maxlen=args.queue_size)
        stream_data = {
            "id": i,
            "queue": queue,
            "pipeline": pipeline,
            "metrics": {
                "processed_frames": 0,
                "stale_frames": 0,
                "queue_wait_ms": [],
                "total_proc_ms": [],
                "stages": collections.defaultdict(list)
            }
        }
        streams.append(stream_data)

    sys_metrics = {"cpu": [], "ram": [], "temp": []}
    monitor_thread = threading.Thread(target=system_monitor, args=(end_event, sys_metrics), daemon=True)
    monitor_thread.start()

    producer_threads = []
    for s in streams:
        t = threading.Thread(
            target=video_producer,
            args=(s["id"], args.video, s["queue"], args.fps, end_event, args.mode),
            daemon=True
        )
        producer_threads.append(t)

    logger.info(f"Starting {args.streams} producers...")
    for t in producer_threads:
        t.start()

    # Give producers a moment to fill queues
    time.sleep(1.0)

    logger.info("Starting pipeline worker loop...")
    start_time = time.perf_counter()
    
    # Fair round-robin scheduling loop
    while time.perf_counter() - start_time < args.duration:
        all_empty = True
        for stream in streams:
            item = stream["queue"].get()
            if item is not None:
                all_empty = False
                frame, enqueue_time = item
                wait_latency = (time.perf_counter() - enqueue_time) * 1000.0
                
                if wait_latency > args.stale_ms:
                    stream["metrics"]["stale_frames"] += 1
                
                proc_start = time.perf_counter()
                res = stream["pipeline"].process_frame(frame)
                proc_latency = (time.perf_counter() - proc_start) * 1000.0
                
                stream["metrics"]["queue_wait_ms"].append(wait_latency)
                stream["metrics"]["total_proc_ms"].append(proc_latency)
                stream["metrics"]["processed_frames"] += 1
                
                if "metrics" in res:
                    for stage_name, stage_latency in res["metrics"].items():
                        stream["metrics"]["stages"][stage_name].append(stage_latency)
        
        if all_empty:
            time.sleep(0.001)

    end_event.set()
    logger.info("Benchmark finished. Aggregating results...")
    
    for t in producer_threads:
        t.join(timeout=2.0)
    monitor_thread.join(timeout=2.0)

    # Report
    total_processed = 0
    total_produced = 0
    total_dropped = 0
    total_stale = 0

    all_total_proc = []
    all_queue_wait = []

    print("\n" + "="*50)
    print(f"BENCHMARK RESULTS ({args.streams} Streams | {args.mode} | {args.fps} FPS/stream)")
    print("="*50)
    
    for s in streams:
        sm = s["metrics"]
        q = s["queue"]
        produced = q.produced_frames
        dropped = q.dropped_frames
        processed = sm["processed_frames"]
        stale = sm["stale_frames"]
        
        total_produced += produced
        total_dropped += dropped
        total_processed += processed
        total_stale += stale
        
        all_total_proc.extend(sm["total_proc_ms"])
        all_queue_wait.extend(sm["queue_wait_ms"])
        
        drop_pct = (dropped / produced * 100) if produced > 0 else 0
        stale_pct = (stale / processed * 100) if processed > 0 else 0
        
        print(f"\n--- Stream {s['id']} ---")
        print(f"Frames: Produced={produced}, Processed={processed}, Dropped={dropped} ({drop_pct:.1f}%), Stale={stale} ({stale_pct:.1f}%)")
        print(f"Max Queue Depth: {q.max_depth} (Limit={q.maxlen})")
        
        proc_stats = calculate_percentiles(sm["total_proc_ms"])
        wait_stats = calculate_percentiles(sm["queue_wait_ms"])
        
        print(f"Total Proc Latency (ms): avg={proc_stats['avg']:.1f}, p50={proc_stats['p50']:.1f}, p90={proc_stats['p90']:.1f}, p99={proc_stats['p99']:.1f}")
        print(f"Queue Wait Latency (ms): avg={wait_stats['avg']:.1f}, p50={wait_stats['p50']:.1f}, p90={wait_stats['p90']:.1f}, p99={wait_stats['p99']:.1f}")
        
        for stage, lats in sm["stages"].items():
            st_stats = calculate_percentiles(lats)
            print(f"  Stage {stage}: avg={st_stats['avg']:.1f}ms, p95={st_stats['p95']:.1f}ms")

    print("\n" + "="*50)
    print("COMBINED METRICS")
    print("="*50)
    
    throughput = total_processed / args.duration
    combined_drop_pct = (total_dropped / total_produced * 100) if total_produced > 0 else 0
    combined_stale_pct = (total_stale / total_processed * 100) if total_processed > 0 else 0
    
    print(f"Total Throughput: {throughput:.2f} FPS (Target: {args.fps * args.streams} FPS)")
    print(f"Total Dropped: {total_dropped}/{total_produced} ({combined_drop_pct:.1f}%)")
    print(f"Total Stale: {total_stale}/{total_processed} ({combined_stale_pct:.1f}%)")
    
    c_proc = calculate_percentiles(all_total_proc)
    c_wait = calculate_percentiles(all_queue_wait)
    print(f"Combined Proc Latency (ms): avg={c_proc['avg']:.1f}, p50={c_proc['p50']:.1f}, p95={c_proc['p95']:.1f}, p99={c_proc['p99']:.1f}")
    print(f"Combined Wait Latency (ms): avg={c_wait['avg']:.1f}, p50={c_wait['p50']:.1f}, p95={c_wait['p95']:.1f}, p99={c_wait['p99']:.1f}")
    
    avg_cpu = statistics.mean(sys_metrics["cpu"]) if sys_metrics["cpu"] else 0.0
    avg_ram = statistics.mean(sys_metrics["ram"]) if sys_metrics["ram"] else 0.0
    avg_temp = statistics.mean(sys_metrics["temp"]) if sys_metrics["temp"] else 0.0
    print(f"System: CPU={avg_cpu:.1f}%, RAM={avg_ram:.1f}%, Temp={avg_temp:.1f}C")
    print("="*50 + "\n")


if __name__ == "__main__":
    main()
