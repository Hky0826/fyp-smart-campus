export function generateWallOverlay(wallGrid, width, height, gridScale) {
    if (!wallGrid) return null;
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = 'rgba(239, 68, 68, 0.4)'; // Tailwind red-500 with 40% opacity
    
    for (let y = 0; y < wallGrid.length; y++) {
        for (let x = 0; x < wallGrid[y].length; x++) {
            if (wallGrid[y][x] === 1) {
                ctx.fillRect(x * gridScale, y * gridScale, gridScale, gridScale);
            }
        }
    }
    
    const img = new window.Image();
    img.src = canvas.toDataURL('image/png');
    return img;
}
