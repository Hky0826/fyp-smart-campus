import cv2
import argparse
import time

def main():
    parser = argparse.ArgumentParser(description="Record a video for multi-stream benchmark.")
    parser.add_argument("--output", "-o", default="test_video.mp4", help="Output video file path.")
    parser.add_argument("--camera", "-c", type=int, default=0, help="Camera device index.")
    parser.add_argument("--duration", "-d", type=int, default=15, help="Duration to record in seconds.")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"Error: Could not open camera {args.camera}")
        return

    # Set resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0 or fps != fps: # Handle NaN or 0
        fps = 30.0
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(args.output, fourcc, fps, (640, 480))

    print(f"Starting recording to {args.output} for {args.duration} seconds.")
    print("Please move IN and OUT of the frame to generate a realistic test video.")
    print("Recording starts in 3 seconds...")
    for i in range(3, 0, -1):
        print(i)
        time.sleep(1)

    print("Recording started! Press 'q' to stop early.")
    start_time = time.time()
    frames_recorded = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame.")
            break

        out.write(frame)
        frames_recorded += 1

        # Calculate remaining time
        elapsed = time.time() - start_time
        remaining = max(0, args.duration - elapsed)

        # Draw a recording indicator on the frame
        cv2.circle(frame, (30, 30), 10, (0, 0, 255), -1)
        cv2.putText(frame, f"REC {remaining:.1f}s", (50, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imshow("Recording", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("Recording stopped by user.")
            break
            
        if elapsed >= args.duration:
            print("Recording time reached.")
            break

    cap.release()
    out.release()
    cv2.destroyAllWindows()
    print(f"Saved {frames_recorded} frames to {args.output}.")

if __name__ == '__main__':
    main()
