/**
 * A* Pathfinding and Geometry Utilities for Campus Navigation System
 */

export function findAStarPath(startPt, endPt, grid, scale) {
  const gridHeight = grid.length;
  if (gridHeight === 0) return null;
  const gridWidth = grid[0].length;

  const startX = Math.max(0, Math.min(gridWidth - 1, Math.floor(startPt.x / scale)));
  const startY = Math.max(0, Math.min(gridHeight - 1, Math.floor(startPt.y / scale)));
  const endX = Math.max(0, Math.min(gridWidth - 1, Math.floor(endPt.x / scale)));
  const endY = Math.max(0, Math.min(gridHeight - 1, Math.floor(endPt.y / scale)));

  let actualStartX = startX;
  let actualStartY = startY;
  if (grid[actualStartY][actualStartX] === 1) {
    const nearby = findNearestTraversable(actualStartX, actualStartY, grid);
    if (nearby) {
      actualStartX = nearby.x;
      actualStartY = nearby.y;
    }
  }

  let actualEndX = endX;
  let actualEndY = endY;
  if (grid[actualEndY][actualEndX] === 1) {
    const nearby = findNearestTraversable(actualEndX, actualEndY, grid);
    if (nearby) {
      actualEndX = nearby.x;
      actualEndY = nearby.y;
    }
  }

  const openSet = [];
  const closedSet = new Set();

  const startNode = {
    x: actualStartX,
    y: actualStartY,
    g: 0,
    h: Math.hypot(actualEndX - actualStartX, actualEndY - actualStartY),
    f: 0,
    parent: null
  };
  startNode.f = startNode.g + startNode.h;

  openSet.push(startNode);
  const getHash = (x, y) => `${x},${y}`;

  const openSetMap = new Map();
  openSetMap.set(getHash(actualStartX, actualStartY), startNode);

  let iterations = 0;
  const MAX_ITERATIONS = 5000;

  while (openSet.length > 0 && iterations < MAX_ITERATIONS) {
    iterations++;
    openSet.sort((a, b) => a.f - b.f);
    const current = openSet.shift();
    const currentHash = getHash(current.x, current.y);
    openSetMap.delete(currentHash);

    if (current.x === actualEndX && current.y === actualEndY) {
      const path = [];
      let temp = current;
      while (temp) {
        path.push({
          x: temp.x * scale + scale / 2,
          y: temp.y * scale + scale / 2
        });
        temp = temp.parent;
      }
      path.reverse();

      path[0] = { x: startPt.x, y: startPt.y };
      path[path.length - 1] = { x: endPt.x, y: endPt.y };
      
      const smoothed = smoothPath(path, grid, scale);
      return smoothed;
    }

    closedSet.add(currentHash);

    const directions = [
      { dx: 1, dy: 0, cost: 1 },
      { dx: -1, dy: 0, cost: 1 },
      { dx: 0, dy: 1, cost: 1 },
      { dx: 0, dy: -1, cost: 1 },
      { dx: 1, dy: 1, cost: Math.SQRT2 },
      { dx: -1, dy: 1, cost: Math.SQRT2 },
      { dx: 1, dy: -1, cost: Math.SQRT2 },
      { dx: -1, dy: -1, cost: Math.SQRT2 }
    ];

    for (const dir of directions) {
      const nx = current.x + dir.dx;
      const ny = current.y + dir.dy;

      if (nx >= 0 && nx < gridWidth && ny >= 0 && ny < gridHeight) {
        if (grid[ny][nx] === 1) continue;

        const neighborHash = getHash(nx, ny);
        if (closedSet.has(neighborHash)) continue;

        if (dir.dx !== 0 && dir.dy !== 0) {
          if (grid[current.y][nx] === 1 || grid[ny][current.x] === 1) {
            continue;
          }
        }

        const tentativeG = current.g + dir.cost;

        let neighborNode = openSetMap.get(neighborHash);
        if (!neighborNode) {
          neighborNode = {
            x: nx,
            y: ny,
            g: tentativeG,
            h: Math.hypot(actualEndX - nx, actualEndY - ny),
            f: 0,
            parent: current
          };
          neighborNode.f = neighborNode.g + neighborNode.h;
          openSet.push(neighborNode);
          openSetMap.set(neighborHash, neighborNode);
        } else if (tentativeG < neighborNode.g) {
          neighborNode.g = tentativeG;
          neighborNode.f = neighborNode.g + neighborNode.h;
          neighborNode.parent = current;
        }
      }
    }
  }

  return null;
}

function findNearestTraversable(startX, startY, grid) {
  const queue = [{ x: startX, y: startY }];
  const visited = new Set([`${startX},${startY}`]);
  const gridHeight = grid.length;
  const gridWidth = grid[0].length;

  while (queue.length > 0) {
    const curr = queue.shift();
    if (grid[curr.y][curr.x] === 0) return curr;

    const dirs = [
      { dx: 1, dy: 0 }, { dx: -1, dy: 0 }, { dx: 0, dy: 1 }, { dx: 0, dy: -1 },
      { dx: 1, dy: 1 }, { dx: -1, dy: 1 }, { dx: 1, dy: -1 }, { dx: -1, dy: -1 }
    ];

    for (const d of dirs) {
      const nx = curr.x + d.dx;
      const ny = curr.y + d.dy;
      if (nx >= 0 && nx < gridWidth && ny >= 0 && ny < gridHeight) {
        const hash = `${nx},${ny}`;
        if (!visited.has(hash)) {
          visited.add(hash);
          queue.push({ x: nx, y: ny });
        }
      }
    }
  }
  return null;
}

export function simplifyPath(path) {
  if (!path || path.length <= 2) return path;

  const simplified = [path[0]];

  for (let i = 1; i < path.length - 1; i++) {
    const prev = path[i - 1];
    const curr = path[i];
    const next = path[i + 1];

    const dx1 = curr.x - prev.x;
    const dy1 = curr.y - prev.y;
    const dx2 = next.x - curr.x;
    const dy2 = next.y - curr.y;

    const crossProduct = dx1 * dy2 - dx2 * dy1;
    if (Math.abs(crossProduct) > 0.001) {
      simplified.push(curr);
    }
  }

  simplified.push(path[path.length - 1]);
  return simplified;
}

export function lineIntersectsWall(p1, p2, grid, scale) {
  const gridHeight = grid.length;
  if (gridHeight === 0) return false;
  const gridWidth = grid[0].length;

  const x1 = Math.max(0, Math.min(gridWidth - 1, Math.floor(p1.x / scale)));
  const y1 = Math.max(0, Math.min(gridHeight - 1, Math.floor(p1.y / scale)));
  const x2 = Math.max(0, Math.min(gridWidth - 1, Math.floor(p2.x / scale)));
  const y2 = Math.max(0, Math.min(gridHeight - 1, Math.floor(p2.y / scale)));

  const dx = Math.abs(x2 - x1);
  const dy = Math.abs(y2 - y1);
  const sx = (x1 < x2) ? 1 : -1;
  const sy = (y1 < y2) ? 1 : -1;
  let err = dx - dy;

  let cx = x1;
  let cy = y1;

  while (true) {
    if (cx >= 0 && cx < gridWidth && cy >= 0 && cy < gridHeight) {
      if (grid[cy][cx] === 1) {
        return true;
      }
    }

    if (cx === x2 && cy === y2) break;
    const e2 = 2 * err;
    if (e2 > -dy) {
      err -= dy;
      cx += sx;
    }
    if (e2 < dx) {
      err += dx;
      cy += sy;
    }
  }

  return false;
}

export function getPathLength(points, scaleRatio) {
  if (!points || points.length < 2) return "0.00";
  let length = 0;
  for (let i = 0; i < points.length - 1; i++) {
    const dx = points[i + 1].x - points[i].x;
    const dy = points[i + 1].y - points[i].y;
    length += Math.hypot(dx, dy);
  }
  return (length * scaleRatio).toFixed(2);
}

export function smoothPath(path, grid, scale) {
  if (!path || path.length <= 2) return path;

  const smoothed = [path[0]];
  let currentIdx = 0;

  while (currentIdx < path.length - 1) {
    let nextIdx = path.length - 1;
    while (nextIdx > currentIdx + 1) {
      if (!lineIntersectsWall(path[currentIdx], path[nextIdx], grid, scale)) {
        break;
      }
      nextIdx--;
    }
    
    smoothed.push(path[nextIdx]);
    currentIdx = nextIdx;
  }

  return smoothed;
}
