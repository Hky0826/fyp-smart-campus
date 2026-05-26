import cv2

cap = cv2.VideoCapture(0) # Change this number if it fails
ret, frame = cap.read()

if ret:
    print("Success! Camera is working and captured a frame.")
else:
    print("Failed to read from camera.")
    
cap.release()