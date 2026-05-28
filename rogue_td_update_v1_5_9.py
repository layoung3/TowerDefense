#!/usr/bin/env python3

import json
import math
import os
import random
import time

import pygame
from collections import deque, defaultdict
from dataclasses import dataclass, field, asdict
from typing import List, Tuple, Dict, Optional

VERSION = "Rogue TD v1.5.9"
SCREEN_W, SCREEN_H = (1280, 720)
FPS = 60
GRID_W, GRID_H = (34, 20)
MARGIN_X, MARGIN_Y = (24, 24)
SIDEBAR_W = 320
SAVE_PATH = "td_save.json"
LEADERBOARD_PATH = "td_leaderboards.json"
COL_BG = (18, 18, 22)
COL_TEXT = (235, 240, 255)
COL_UI = (30, 32, 42)
COL_PATH = (70, 80, 100)
COL_PAD = (44, 48, 62)
COL_TOWER_RING = (255, 255, 255)
COL_ENEMY = (240, 120, 120)
COL_BOSS = (255, 180, 60)
COL_HP_BG = (45, 18, 18)
COL_HP = (210, 50, 50)
COL_EXIT = (200, 80, 80)
COL_START = (80, 180, 120)
COL_PREVIEW_OK = (120, 210, 120)
COL_PREVIEW_BAD = (210, 120, 120)
COL_PANEL = (22, 24, 30)
COL_DIM = (0, 0, 0)
MODE_SINGLE = "Single Path"
MODE_MULTI = "Multi Entrances"
ALL_MODES = [MODE_SINGLE, MODE_MULTI]
BUILD, COMBAT = (0, 1)
DIFFICULTIES = ["Easy", "Normal", "Hard"]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def neighbors4(x, y):
    return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]


def bfs_next_step(grid, w, h, start, goal):
    if start == goal:
        return start
    sx, sy = start
    gx, gy = goal
    q = deque([(sx, sy)])
    came = {(sx, sy): None}
    while q:
        x, y = q.popleft()
        for nx, ny in neighbors4(x, y):
            if (
                0 <= nx < w
                and 0 <= ny < h
                and (grid[ny][nx] == 1)
                and ((nx, ny) not in came)
            ):
                came[nx, ny] = (x, y)
                if (nx, ny) == (gx, gy):
                    cur = (nx, ny)
                    prev = came[cur]
                    while prev and prev != (sx, sy):
                        cur = prev
                        prev = came[cur]
                    return cur
                q.append((nx, ny))
    best = None
    bestd = 1000000000.0
    for nx, ny in neighbors4(sx, sy):
        if 0 <= nx < w and 0 <= ny < h and (grid[ny][nx] == 1):
            d = abs(nx - gx) + abs(ny - gy)
            if d < bestd:
                bestd = d
                best = (nx, ny)
    return best or start


@dataclass
class TowerSpec:
    key: str
    name: str
    base_cost: int
    dmg: float
    rof: float
    rng: int
    color: Tuple[int, int, int]
    slow: float = 0.0
    splash: int = 0


@dataclass
class Tower:
    tkey: str
    gx: int
    gy: int
    level: int = 1
    xp: float = 0.0
    dmg_mod: float = 0.0
    rof_mod: float = 0.0
    rng_mod: int = 0
    last_shot: float = 0.0
    selected: bool = False
    dmg_done: float = 0.0
    shots: int = 0
    hits: int = 0
    poison_bonus: float = 0.0
    chain_bounces: int = 0
    crit_chance: float = 0.0
    armor_pierce: float = 0.0
    target_mode: str = "First"
    prio: str = "None"
    label_idx: int = 0

    def base_stats(self, spec: "TowerSpec"):
        dmg = spec.dmg * (1.0 + 0.15 * (self.level - 1) + self.dmg_mod)
        rof = spec.rof * (1.0 + 0.1 * (self.level - 1) + self.rof_mod)
        rng = spec.rng + self.rng_mod
        return (dmg, rof, rng)


@dataclass
class Enemy:
    gx: int
    gy: int
    hp: float
    max_hp: float
    speed: float
    etype: str = "grunt"
    boss: bool = False
    armor: float = 0.0
    slow_until: float = 0.0
    path_goal: Tuple[int, int] = (0, 0)
    progress: float = 0.0
    id: int = 0
    dots: List[Tuple[float, float]] = field(default_factory=list)
    tag_fast: bool = False
    tag_swarm: bool = False


@dataclass
class SpawnGroup:
    etype: str
    count: int
    hp: float
    speed: float
    armor: float = 0.0
    boss: bool = False


@dataclass
class FloatingText:
    x: float
    y: float
    text: str
    ttl: float
    vy: float
    color: Tuple[int, int, int] = (255, 255, 255)


@dataclass
class Projectile:
    sx: float
    sy: float
    ex: float
    ey: float
    ttl: float
    max_ttl: float
    color: Tuple[int, int, int]
    radius: int = 3


@dataclass
class RunState:
    mode: str = MODE_SINGLE
    difficulty: str = "Normal"
    coins: int = 150
    wave: int = 1
    lives: int = 20
    phase: int = BUILD
    fast: bool = False
    unlocked: Dict[str, bool] = field(
        default_factory=lambda: {
            "arrow": True,
            "cannon": True,
            "frost": False,
            "storm": False,
            "poison": False,
            "chain": False,
            "sniper": False,
        }
    )
    grid: List[List[int]] = field(default_factory=list)
    starts: List[Tuple[int, int]] = field(default_factory=list)
    exits: List[Tuple[int, int]] = field(default_factory=list)
    towers: List[Tower] = field(default_factory=list)
    enemies: List[Enemy] = field(default_factory=list)
    spawn_groups: List[SpawnGroup] = field(default_factory=list)
    next_spawn_t: float = 0.0
    spawn_group_idx: int = 0
    spawn_rot: int = 0
    score: int = 0
    name_entry: str = ""
    ui_mode: str = "none"
    ui_data: dict = field(default_factory=dict)
    wave_clear_at: float = 0.0
    relics: Dict[str, float] = field(default_factory=lambda: defaultdict(float))


class RogueTD:

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption(VERSION)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 18)
        self.font_small = pygame.font.SysFont("consolas", 16)
        self.font_big = pygame.font.SysFont("consolas", 28)
        self.running = True
        self.state = "menu"
        self.menu_sel = 0
        self.mode_sel = 0
        self.diff_sel = 1
        self.selected_tkey = None
        self._last_log = ""
        self.ftexts: List[FloatingText] = []
        self.projectiles: List[Projectile] = []
        self.specs = {
            "arrow": TowerSpec("arrow", "Arrow", 50, 9, 1.3, 4, (100, 190, 255)),
            "cannon": TowerSpec(
                "cannon", "Cannon", 90, 22, 0.40, 6, (220, 170, 90), splash=2
            ),
            "frost": TowerSpec(
                "frost", "Frost", 60, 5, 0.9, 4, (160, 220, 255), slow=0.45
            ),
            "storm": TowerSpec("storm", "Storm", 110, 6, 2.2, 5, (200, 120, 240)),
            "poison": TowerSpec("poison", "Poison", 70, 3, 1.0, 4, (120, 220, 120)),
            "chain": TowerSpec("chain", "Chain", 120, 5, 1.6, 4, (200, 200, 120)),
            "sniper": TowerSpec("sniper", "Sniper", 140, 28, 0.35, 7, (220, 120, 160)),
        }
        self.short = {
            "arrow": "A",
            "cannon": "C",
            "frost": "F",
            "storm": "S",
            "poison": "P",
            "chain": "Ch",
            "sniper": "Sn",
        }
        self.run: Optional[RunState] = None
        self.load_save_if_exists()

    def tile_size(self):
        avail_w = SCREEN_W - SIDEBAR_W - 2 * MARGIN_X
        avail_h = SCREEN_H - 2 * MARGIN_Y
        t_w = max(16, avail_w // GRID_W)
        t_h = max(16, avail_h // GRID_H)
        return int(min(40, t_w, t_h))

    def grid_to_px(self, gx, gy):
        T = self.tile_size()
        return (MARGIN_X + gx * T, MARGIN_Y + gy * T)

    def save_run(self):
        if not self.run:
            return
        json.dump({"version": VERSION, "run": asdict(self.run)}, open(SAVE_PATH, "w"))

    def load_save_if_exists(self):
        if os.path.exists(SAVE_PATH):
            try:
                data = json.load(open(SAVE_PATH, "r"))
                if data.get("version") != VERSION:
                    self.run = None
                else:
                    self.run = RunState(**data["run"])
            except Exception:
                self.run = None

    def clear_save(self):
        if os.path.exists(SAVE_PATH):
            try:
                os.remove(SAVE_PATH)
            except:
                pass

    def add_leader(self, mode, name, score):
        board = {}
        if os.path.exists(LEADERBOARD_PATH):
            try:
                board = json.load(open(LEADERBOARD_PATH, "r"))
            except:
                board = {}
        board.setdefault(mode, []).append(
            {"name": name, "score": score, "ts": int(time.time())}
        )
        board[mode] = sorted(board[mode], key=lambda e: e["score"], reverse=True)[:20]
        json.dump(board, open(LEADERBOARD_PATH, "w"))

    def get_board(self, mode):
        if os.path.exists(LEADERBOARD_PATH):
            try:
                return json.load(open(LEADERBOARD_PATH, "r")).get(mode, [])
            except:
                return []
        return []

    def _carve_line(self, grid, start, goal):
        x, y = start
        gx, gy = goal
        grid[y][x] = 1
        while x != gx:
            x += 1 if gx > x else -1
            grid[y][x] = 1
        while y != gy:
            y += 1 if gy > y else -1
            grid[y][x] = 1

    def _route_metrics(self, route):
        left_moves = 0
        vertical_moves = 0
        turns = 0
        last_dir = None

        for a, b in zip(route, route[1:]):
            dx = b[0] - a[0]
            dy = b[1] - a[1]
            if dx < 0:
                left_moves += 1
            if dy != 0:
                vertical_moves += 1
            direction = (clamp(dx, -1, 1), clamp(dy, -1, 1))
            if last_dir is not None and direction != last_dir:
                turns += 1
            last_dir = direction

        return left_moves, vertical_moves, turns

    def _weighted_choice(self, options, weights, rng):
        total = sum(weights)
        if total <= 0:
            return rng.choice(options)

        pick = rng.uniform(0, total)
        running = 0.0
        for option, weight in zip(options, weights):
            running += weight
            if pick <= running:
                return option
        return options[-1]

    def _generate_coarse_route(self, col_count, row_count, start_row, end_row, rng):
        goal = (col_count - 1, end_row)

        for _ in range(800):
            min_nodes = rng.randint(16, 23)
            max_nodes = rng.randint(25, 42)
            route = [(0, start_row)]
            visited = set(route)

            for _step in range(max_nodes):
                current = route[-1]
                left_moves, vertical_moves, turns = self._route_metrics(route)

                if (
                    current == goal
                    and len(route) >= min_nodes
                    and vertical_moves >= 4
                    and turns >= 5
                    and (left_moves >= 1 or rng.random() < 0.20)
                ):
                    return route

                candidates = []
                weights = []
                distance_now = abs(current[0] - goal[0]) + abs(current[1] - goal[1])
                remaining_steps = max_nodes - len(route)

                for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    nx = current[0] + dx
                    ny = current[1] + dy
                    nxt = (nx, ny)

                    if not (0 <= nx < col_count and 0 <= ny < row_count):
                        continue
                    if nxt in visited:
                        continue

                    distance_new = abs(nx - goal[0]) + abs(ny - goal[1])
                    if remaining_steps <= distance_now and distance_new > distance_now:
                        continue
                    if len(route) < min_nodes and nx == goal[0] and ny == goal[1]:
                        continue

                    weight = 1.0

                    if dx > 0:
                        weight += 2.4
                    elif dx < 0 and len(route) > 4:
                        weight += 1.8

                    if dy != 0:
                        weight += 2.1

                    if distance_new < distance_now:
                        weight += 1.6
                    elif len(route) < min_nodes:
                        weight += 0.8

                    if left_moves == 0 and len(route) > 7 and dx < 0:
                        weight += 3.0
                    if vertical_moves < 4 and dy != 0:
                        weight += 2.5
                    if turns < 5:
                        prev = route[-2] if len(route) >= 2 else None
                        if prev is not None:
                            prev_dir = (current[0] - prev[0], current[1] - prev[1])
                            new_dir = (dx, dy)
                            if new_dir != prev_dir:
                                weight += 1.8

                    candidates.append(nxt)
                    weights.append(weight)

                if not candidates:
                    break

                nxt = self._weighted_choice(candidates, weights, rng)
                route.append(nxt)
                visited.add(nxt)

        return self._fallback_coarse_route(col_count, row_count, start_row, end_row, rng)

    def _fallback_coarse_route(self, col_count, row_count, start_row, end_row, rng):
        route = [(0, start_row)]
        used = set(route)
        row = start_row
        col = 0

        while col < col_count - 1:
            move_right = rng.randint(2, 4)
            for _ in range(move_right):
                if col >= col_count - 1:
                    break
                col += 1
                if (col, row) not in used:
                    route.append((col, row))
                    used.add((col, row))

            choices = [r for r in range(row_count) if r != row]
            choices.sort(key=lambda r: (abs(r - row), rng.random()))
            target_row = choices[min(len(choices) - 1, rng.randint(1, 3))]
            step = 1 if target_row > row else -1
            while row != target_row:
                row += step
                if (col, row) not in used:
                    route.append((col, row))
                    used.add((col, row))

            if rng.random() < 0.55 and col > 2:
                col -= 1
                if (col, row) not in used:
                    route.append((col, row))
                    used.add((col, row))

        while row != end_row:
            step = 1 if end_row > row else -1
            row += step
            if (col, row) not in used:
                route.append((col, row))
                used.add((col, row))

        if route[-1] != (col_count - 1, end_row):
            route.append((col_count - 1, end_row))
        return route

    def _cells_from_route(self, route, xs, ys, goal):
        cells = []
        current = (xs[route[0][0]], ys[route[0][1]])
        cells.append(current)

        points = [(xs[col], ys[row]) for col, row in route[1:]]
        points.append(goal)

        for point in points:
            x, y = current
            gx, gy = point

            while x != gx:
                x += 1 if gx > x else -1
                cell = (x, y)
                if not cells or cells[-1] != cell:
                    cells.append(cell)

            while y != gy:
                y += 1 if gy > y else -1
                cell = (x, y)
                if not cells or cells[-1] != cell:
                    cells.append(cell)

            current = (gx, gy)

        return cells

    def _is_single_path(self, grid, start, goal):
        path_cells = {
            (x, y)
            for y in range(len(grid))
            for x in range(len(grid[0]))
            if grid[y][x] == 1
        }

        if start not in path_cells or goal not in path_cells:
            return False

        endpoints = 0
        for x, y in path_cells:
            degree = 0
            for nx, ny in neighbors4(x, y):
                if (nx, ny) in path_cells:
                    degree += 1

            if (x, y) in (start, goal):
                if degree != 1:
                    return False
                endpoints += 1
            elif degree != 2:
                return False

        if endpoints != 2:
            return False

        seen = set()
        queue = deque([start])
        while queue:
            cell = queue.popleft()
            if cell in seen:
                continue
            seen.add(cell)
            x, y = cell
            for nx, ny in neighbors4(x, y):
                if (nx, ny) in path_cells and (nx, ny) not in seen:
                    queue.append((nx, ny))

        return len(seen) == len(path_cells)

    def _carve_path(self, grid, w, h, start, goal, rng):
        sx, sy = start
        gx, gy = goal

        xs = list(range(1, w - 2, 3))
        if xs[-1] != w - 3:
            xs.append(w - 3)

        base_rows = list(range(2, h - 2, 3))
        ys = sorted(set(base_rows + [sy, gy]))
        start_row = min(range(len(ys)), key=lambda i: abs(ys[i] - sy))
        end_row = min(range(len(ys)), key=lambda i: abs(ys[i] - gy))

        best_cells = None
        for _ in range(60):
            temp_grid = [[0] * w for _ in range(h)]
            route = self._generate_coarse_route(len(xs), len(ys), start_row, end_row, rng)
            cells = self._cells_from_route(route, xs, ys, (gx, gy))

            valid = True
            seen = set()
            for x, y in cells:
                if not (0 <= x < w and 0 <= y < h):
                    valid = False
                    break
                if (x, y) in seen:
                    valid = False
                    break
                seen.add((x, y))
                temp_grid[y][x] = 1

            if valid and self._is_single_path(temp_grid, start, goal):
                best_cells = cells
                break

        if best_cells is None:
            self._carve_line(grid, start, goal)
            return

        for x, y in best_cells:
            grid[y][x] = 1

    def _connect_to_any_path(self, grid, w, h, start, rng):
        x, y = start
        grid[y][x] = 1
        for _ in range(w * h * 6):
            for nx, ny in neighbors4(x, y):
                if (
                    0 <= nx < w
                    and 0 <= ny < h
                    and (grid[ny][nx] == 1)
                    and ((nx, ny) != (x, y))
                ):
                    return
            dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
            if x <= 2:
                dirs = [(1, 0), (0, 1), (0, -1)]
            if x >= w - 3:
                dirs = [(-1, 0), (0, 1), (0, -1)]
            if y <= 2:
                dirs = [(0, 1), (1, 0), (-1, 0)]
            if y >= h - 3:
                dirs = [(0, -1), (1, 0), (-1, 0)]
            dx, dy = random.choice(dirs)
            x = clamp(x + dx, 1, w - 2)
            y = clamp(y + dy, 1, h - 2)
            grid[y][x] = 1

    def new_map(self, mode):
        w, h = (GRID_W, GRID_H)
        grid = [[0] * w for _ in range(h)]
        starts = []
        exits = []
        rng = random.Random(int(time.time() * 1000) % 2**32)
        if mode == MODE_SINGLE:
            lane_rows = list(range(2, h - 2, 3))
            middle_rows = lane_rows[1:-1] or lane_rows

            sx, sy = (1, rng.choice(middle_rows))
            exit_choices = [row for row in lane_rows if row != sy]
            gx, gy = (w - 2, rng.choice(exit_choices))
            starts = [(sx, sy)]
            exits = [(gx, gy)]
            self._carve_path(grid, w, h, (sx, sy), (gx, gy), rng)
        else:
            sside = rng.choice(["L", "T", "B"])
            sx = 1 if sside == "L" else rng.randint(2, w - 3)
            sy = rng.randint(2, h - 3) if sside == "L" else 1 if sside == "T" else h - 2
            eside = rng.choice(["R", "B"])
            gx = w - 2 if eside == "R" else rng.randint(2, w - 3)
            gy = rng.randint(2, h - 3) if eside == "R" else h - 2
            starts.append((sx, sy))
            exits.append((gx, gy))
            self._carve_path(grid, w, h, (sx, sy), (gx, gy), rng)
            for _ in range(rng.randint(1, 2)):
                side = rng.choice(["L", "T", "B"])
                xs = 1 if side == "L" else rng.randint(2, w - 3)
                ys = (
                    rng.randint(2, h - 3)
                    if side == "L"
                    else 1 if side == "T" else h - 2
                )
                starts.append((xs, ys))
                self._connect_to_any_path(grid, w, h, (xs, ys), rng)
            for _ in range(rng.randint(0, 1)):
                side = rng.choice(["R", "B"])
                xe = w - 2 if side == "R" else rng.randint(2, w - 3)
                ye = rng.randint(2, h - 3) if side == "R" else h - 2
                exits.append((xe, ye))
                self._connect_to_any_path(grid, w, h, (xe, ye), rng)
        for sx, sy in starts:
            grid[sy][sx] = 1
        for ex, ey in exits:
            grid[ey][ex] = 1
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if grid[y][x] == 1:
                    continue
                mind = 99
                for nx, ny in [
                    (x + 1, y),
                    (x - 1, y),
                    (x, y + 1),
                    (x, y - 1),
                    (x + 2, y),
                    (x - 2, y),
                    (x, y + 2),
                    (x, y - 2),
                ]:
                    if 0 <= nx < w and 0 <= ny < h and (grid[ny][nx] == 1):
                        d = abs(nx - x) + abs(ny - y)
                        mind = min(mind, d)
                if 1 <= mind <= 2:
                    grid[y][x] = 2
        return (grid, starts, exits)

    def new_run(self, mode):
        diff = DIFFICULTIES[self.diff_sel]
        grid, starts, exits = self.new_map(mode)
        base_coins = {"Easy": 240, "Normal": 180, "Hard": 150}[diff]
        lives = {"Easy": 30, "Normal": 20, "Hard": 15}[diff]
        self.run = RunState(
            mode=mode,
            difficulty=diff,
            coins=base_coins,
            lives=lives,
            grid=grid,
            starts=starts,
            exits=exits,
        )
        self.state = "game"
        self.clear_save()
        self.log(f"{diff} run started")

    def continue_run(self):
        if self.run:
            self.state = "game"

    def end_run(self):
        if not self.run:
            return
        self.state = "name_entry"
        self.run.name_entry = ""

    def base_wave_params(self, wave):
        diff_mul = {"Easy": 0.85, "Normal": 1.0, "Hard": 1.12}[self.run.difficulty]
        late_wave = max(0, wave - 45)
        very_late_wave = max(0, wave - 75)
        speed_wave = min(wave, 50)

        mid_wave = max(0, wave - 25)
        count = max(
            6,
            5
            + int(2.25 * math.sqrt(wave))
            + int(0.08 * wave)
            + int(0.60 * math.sqrt(very_late_wave)),
        )
        hp_scale = (
            1.0 + 0.095 * (wave - 1) + 0.0020 * mid_wave**2 + 0.0060 * late_wave**2
        )
        hp = 14 * hp_scale * diff_mul
        spd = (1.02 + 0.02 * (speed_wave - 1)) * (0.95 + 0.05 * diff_mul)
        return (count, hp, spd)

    def composition_for_wave(self, wave):
        count, hp, spd = self.base_wave_params(wave)
        groups: List[SpawnGroup] = []
        grunt = int(count * 0.6)
        runner = int(count * 0.2) if wave >= 3 and wave % 2 == 0 else 0
        tank = int(count * 0.15) if wave >= 5 and wave % 3 == 0 else 0
        shield = int(count * 0.12) if wave >= 7 and wave % 4 == 0 else 0
        swarm = int(count * 0.25) if wave >= 9 and wave % 2 == 1 else 0
        used = grunt + runner + tank + shield + swarm
        if used < count:
            grunt += count - used
        if grunt > 0:
            groups.append(SpawnGroup("grunt", grunt, hp, spd, armor=0.0))
        if runner > 0:
            groups.append(SpawnGroup("runner", runner, hp * 0.6, spd * 1.55, armor=0.0))
        if tank > 0:
            groups.append(SpawnGroup("tank", tank, hp * 1.9, spd * 0.68, armor=0.0))
        if shield > 0:
            groups.append(SpawnGroup("shield", shield, hp * 1.2, spd * 0.92, armor=3.0))
        if swarm > 0:
            groups.append(SpawnGroup("swarm", swarm, hp * 0.5, spd * 1.25, armor=0.0))
        if wave % 5 == 0:
            groups.append(
                SpawnGroup("boss", 1, hp * 3.0, spd * 1.05, armor=3.0, boss=True)
            )
        return groups

    def preview_text_for_wave(self, wave):
        groups = self.composition_for_wave(wave)
        agg = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
        for g in groups:
            agg[g.etype][0] += g.count
            agg[g.etype][1] += g.hp * g.count
            agg[g.etype][2] += g.speed * g.count
            agg[g.etype][3] += g.armor * g.count
        lines = []
        for et in ["grunt", "runner", "tank", "shield", "swarm", "boss"]:
            if et in agg:
                c, H, S, A = agg[et]
                H /= c
                S /= c
                A /= c
                name = et.capitalize()
                lines.append(
                    f"{name}: x{c}  HP {int(H)}  SPD {S:.2f}"
                    + (f"  ARM {A:.1f}" if A > 0 else "")
                )
        return (lines, groups)

    def spawn_gap_for_wave(self, wave):
        speed_wave = min(max(1, wave), 50)
        progress = (speed_wave - 1) / 49.0
        min_gap = 1.45 + (0.64 - 1.45) * progress
        max_gap = 2.30 + (1.25 - 2.30) * progress

        if wave <= 2:
            min_gap, max_gap = 1.55, 2.45
        elif wave <= 5:
            min_gap, max_gap = 1.35, 2.15

        gap = random.uniform(min_gap, max_gap)
        if random.random() < 0.22:
            gap += random.uniform(0.35, 1.35)
        return gap

    def start_is_clear(self, start_index, etype=None):
        r = self.run
        sx, sy = r.starts[start_index]
        for e in r.enemies:
            if etype is not None and e.etype != etype:
                continue
            if abs(e.gx - sx) + abs(e.gy - sy) <= 1:
                return False
        return True

    def start_wave(self):
        r = self.run
        if not r or r.phase != BUILD or r.ui_mode != "none":
            return
        r.phase = COMBAT
        r.wave_clear_at = 0.0
        r.enemies.clear()
        _, groups = self.preview_text_for_wave(r.wave)
        r.spawn_groups = [
            SpawnGroup(g.etype, g.count, g.hp, g.speed, g.armor, g.boss) for g in groups
        ]
        r.spawn_group_idx = 0
        r.spawn_rot = 0
        r.next_spawn_t = time.time() + self.spawn_gap_for_wave(r.wave)
        self.log(f"Wave {r.wave} begins!")

    def finish_wave(self):
        r = self.run
        r.phase = BUILD
        r.wave_clear_at = 0.0
        base_reward = {"Easy": 95, "Normal": 90, "Hard": 85}[r.difficulty]
        reward = base_reward + 12 * r.wave + int(8 * math.sqrt(r.wave))
        r.coins += reward
        r.score += 55 + 14 * r.wave
        just_cleared = r.wave
        r.wave += 1
        self.log(f"Wave cleared! +{reward} coins")
        r.ui_data["pending_relic"] = just_cleared % 10 == 0
        self.open_recap_modal()

    def log(self, msg):
        self._last_log = msg

    def place_tower(self, gx, gy):
        r = self.run
        if r.phase != BUILD or r.ui_mode != "none":
            return
        if not (0 <= gx < GRID_W and 0 <= gy < GRID_H):
            return
        for t in r.towers:
            t.selected = False
        for t in r.towers:
            if t.gx == gx and t.gy == gy:
                t.selected = True
                self.log(f"Selected {self.specs[t.tkey].name}")
                return
        if r.grid[gy][gx] != 2:
            return
        if any((t.gx == gx and t.gy == gy for t in r.towers)):
            return
        if not self.selected_tkey or not r.unlocked.get(self.selected_tkey, False):
            return
        spec = self.specs[self.selected_tkey]
        cost = spec.base_cost
        if r.coins < cost:
            self.log(f"Not enough coins for {spec.name} (need {cost}).")
            return
        r.coins -= cost
        idx = 1 + sum((1 for t in r.towers if t.tkey == self.selected_tkey))
        tw = Tower(self.selected_tkey, gx, gy, label_idx=idx)
        r.towers.append(tw)
        self.log(f"Placed {spec.name} #{idx} ({cost})")

    def sell_tower(self, gx, gy):
        r = self.run
        for i, t in enumerate(r.towers):
            if t.gx == gx and t.gy == gy:
                refund = int(self.specs[t.tkey].base_cost * 0.6)
                r.coins += refund
                r.towers.pop(i)
                self.log(f"Sold (+{refund})")
                return

    def enemy_to_exit(self, e):
        r = self.run
        best = None
        bestd = 1000000000.0
        for ex in r.exits:
            d = abs(e.gx - ex[0]) + abs(e.gy - ex[1])
            if d < bestd:
                bestd = d
                best = ex
        return best

    def spawn_from_group(self):
        r = self.run
        if not r.spawn_groups:
            return False
        for _ in range(len(r.spawn_groups)):
            g = r.spawn_groups[r.spawn_group_idx]
            if g.count > 0:
                si = r.spawn_rot % max(1, len(r.starts))
                if not self.start_is_clear(si, g.etype):
                    return True
                self.spawn_enemy(si, g)
                g.count -= 1
                r.spawn_group_idx = (r.spawn_group_idx + 1) % len(r.spawn_groups)
                r.spawn_rot += 1
                return any((gr.count > 0 for gr in r.spawn_groups))
            else:
                r.spawn_group_idx = (r.spawn_group_idx + 1) % len(r.spawn_groups)
        return False

    def spawn_enemy(self, si, g: SpawnGroup):
        r = self.run
        sx, sy = r.starts[si]
        e = Enemy(
            sx,
            sy,
            g.hp,
            g.hp,
            g.speed,
            etype=g.etype,
            boss=g.boss,
            armor=g.armor,
            id=len(r.enemies) + r.wave * 1000,
        )
        e.tag_fast = g.etype in ("runner", "swarm")
        e.tag_swarm = g.etype == "swarm"
        e.path_goal = self.enemy_to_exit(e)
        r.enemies.append(e)

    def tick_enemies(self, dt):
        r = self.run
        now = time.time()
        if (
            r.phase == COMBAT
            and now >= r.next_spawn_t
            and any((gr.count > 0 for gr in r.spawn_groups))
        ):
            still_left = self.spawn_from_group()
            if still_left:
                r.next_spawn_t = now + self.spawn_gap_for_wave(r.wave)
        for e in r.enemies[:]:
            if e.dots:
                e.dots = [(dps, until) for dps, until in e.dots if until > now]
                total_dps = sum((dps for dps, until in e.dots))
                if total_dps > 0:
                    dmg = total_dps * dt
                    e.hp -= dmg
                    self.spawn_text(
                        *self.enemy_center(e), f"{int(dmg)}", (180, 255, 140)
                    )
                    if e.hp <= 0:
                        r.enemies.remove(e)
                        continue
            slow_mod = 0.6 if e.slow_until > now and (not e.boss) else 1.0
            spd = e.speed * slow_mod
            e.progress += spd * dt
            while e.progress >= 1.0:
                e.progress -= 1.0
                nx, ny = bfs_next_step(
                    r.grid, GRID_W, GRID_H, (e.gx, e.gy), e.path_goal
                )
                if (nx, ny) == (e.gx, e.gy):
                    break
                e.gx, e.gy = (nx, ny)
            if (e.gx, e.gy) == e.path_goal:
                r.enemies.remove(e)
                r.lives -= 1
                if r.lives <= 0:
                    self.end_run()
        if (
            r.phase == COMBAT
            and all((gr.count <= 0 for gr in r.spawn_groups))
            and (not r.enemies)
            and (r.lives > 0)
        ):
            if r.wave_clear_at <= 0.0:
                r.wave_clear_at = now + 1.75
                self.log("Wave cleared! Showing final shots...")
            elif now >= r.wave_clear_at:
                self.finish_wave()

    def enemy_center(self, e):
        T = self.tile_size()
        px, py = self.grid_to_px(e.gx, e.gy)
        return (px + T // 2, py + T // 2)

    def spawn_text(self, x, y, text, color=(255, 255, 255)):
        self.ftexts.append(FloatingText(x, y, text, ttl=0.9, vy=-28, color=color))

    def spawn_projectile(self, tower: Tower, target: Enemy, color, radius=3):
        T = self.tile_size()
        sx, sy = self.grid_to_px(tower.gx, tower.gy)
        ex, ey = self.enemy_center(target)
        self.projectiles.append(
            Projectile(
                sx=sx + T // 2,
                sy=sy + T // 2,
                ex=ex,
                ey=ey,
                ttl=0.16,
                max_ttl=0.16,
                color=color,
                radius=radius,
            )
        )

    def upgrade_cost(self, tower: Tower):
        investment = (
            tower.dmg_mod / 0.1
            + tower.rof_mod / 0.1
            + tower.rng_mod
            + tower.poison_bonus
            + tower.chain_bounces
            + tower.crit_chance / 0.05
        )
        return int(35 + 12 * (tower.level - 1) + 14 * investment)

    def calc_stats(self, t: Tower):
        spec = self.specs[t.tkey]
        dmg, rof, rng = t.base_stats(spec)
        r = self.run
        rel = r.relics
        dmg *= 1.0 + rel.get("global_dmg", 0.0)
        rof *= 1.0 + rel.get("global_rof", 0.0)
        rng += int(rel.get("global_rng", 0.0))
        return (dmg, rof, rng)

    def tower_targets(self, t):
        r = self.run
        spec = self.specs[t.tkey]
        dmg, rof, rng = self.calc_stats(t)
        R2 = rng * rng
        cand = []
        for e in r.enemies:
            dx = e.gx - t.gx
            dy = e.gy - t.gy
            if dx * dx + dy * dy <= R2:
                dist_to_exit = min(
                    (abs(e.gx - ex) + abs(e.gy - ey) for ex, ey in r.exits)
                )
                cand.append((e, dist_to_exit))
        if not cand:
            return (None, dmg, rof, spec)
        subset = cand
        if t.prio != "None":
            if t.prio == "Boss":
                subset = [ed for ed in cand if ed[0].boss]
            elif t.prio == "Fast":
                subset = [ed for ed in cand if ed[0].tag_fast]
            elif t.prio == "Armored":
                subset = [ed for ed in cand if ed[0].armor > 0.0]
            elif t.prio == "Swarm":
                subset = [ed for ed in cand if ed[0].tag_swarm]
            if not subset:
                subset = cand
        mode = t.target_mode
        if mode == "First":
            target = min(subset, key=lambda ed: ed[1])[0]
        elif mode == "Last":
            target = max(subset, key=lambda ed: ed[1])[0]
        elif mode == "Strongest":
            target = max(subset, key=lambda ed: ed[0].hp)[0]
        else:
            target = min(
                subset, key=lambda ed: abs(ed[0].gx - t.gx) + abs(ed[0].gy - t.gy)
            )[0]
        return (target, dmg, rof, spec)

    def on_kill(self, t, spec):
        r = self.run
        r.coins += 5 + r.wave // 3 + int(r.relics.get("coin_kill", 0.0))
        r.score += 3 + r.wave // 2
        t.xp += 1.0
        self.spawn_text(
            *self.enemy_center(self._dummy_enemy_for_pos(t.gx, t.gy)),
            "K.O.",
            (255, 220, 120),
        )
        xp_needed = 8 + 4 * t.level + 2 * (t.level - 1) ** 2
        if t.xp >= xp_needed and t.level < 7:
            t.level += 1
            t.xp = 0.0
            self.log(f"{spec.name} #{t.label_idx} leveled to {t.level}!")

    def _dummy_enemy_for_pos(self, gx, gy):
        return Enemy(gx, gy, 1, 1, 0.0)

    def _register_shot(self, t: Tower):
        t.shots += 1

    def _register_hit(self, t: Tower, count: int = 1):
        t.hits += count

    def deal_damage(self, t, target, amount, spec, splash=False):
        if not splash:
            radius = 5 if spec.key == "cannon" else 3
            self.spawn_projectile(t, target, spec.color, radius=radius)
        eff = amount * (1.0 - min(0.8, target.armor * (1.0 - t.armor_pierce) / 10.0))
        target.hp -= eff
        t.dmg_done += max(0.0, min(eff, target.hp + eff))
        self.spawn_text(
            *self.enemy_center(target),
            f"{int(eff)}",
            (255, 220, 220) if not splash else (255, 200, 160),
        )
        self._register_hit(t, 1)
        slow_amt = spec.slow
        if spec.key == "frost":
            slow_amt = min(0.9, slow_amt + self.run.relics.get("frost_slow", 0.0))
        if slow_amt > 0 and (not splash) and (not target.boss):
            target.slow_until = time.time() + 1.1
        if target.hp <= 0:
            try:
                self.run.enemies.remove(target)
            except:
                pass
            self.on_kill(t, spec)

    def tick_towers(self, dt):
        r = self.run
        now = time.time()
        for t in r.towers:
            target, dmg, rof, spec = self.tower_targets(t)
            if not target:
                continue
            delay = 1.0 / max(0.1, rof)
            if now - t.last_shot >= delay:
                t.last_shot = now
                self._register_shot(t)
                key = t.tkey
                if key == "cannon" and spec.splash > 0:
                    hits = 0
                    for e in r.enemies[:]:
                        if abs(e.gx - target.gx) + abs(e.gy - target.gy) <= spec.splash:
                            self.deal_damage(
                                t,
                                e,
                                dmg * (0.66 if e is not target else 1.0),
                                spec,
                                splash=e is not target,
                            )
                            hits += 1
                    if hits > 1:
                        self._register_hit(t, hits - 1)
                elif key == "poison":
                    self.deal_damage(
                        t,
                        target,
                        dmg * 0.6 + 0.5 * self.run.relics.get("poison_potency", 0.0),
                        spec,
                    )
                    dot = (
                        2.0
                        + 1.0 * t.poison_bonus
                        + self.run.relics.get("poison_potency", 0.0)
                    )
                    target.dots.append((dot, now + 2.5))
                elif key == "chain":
                    extra = int(self.run.relics.get("chain_bounce", 0.0))
                    remaining = t.chain_bounces + 2 + extra
                    victim = target
                    dealt_first = False
                    visited = set()
                    local_hits = 0
                    while remaining > 0 and victim:
                        self.deal_damage(
                            t, victim, dmg * (0.85 if dealt_first else 1.0), spec
                        )
                        visited.add(victim.id)
                        dealt_first = True
                        remaining -= 1
                        local_hits += 1
                        nxt = None
                        bestd = 1000000000.0
                        for e in r.enemies:
                            if e.id in visited:
                                continue
                            d = abs(e.gx - victim.gx) + abs(e.gy - victim.gy)
                            if d <= 2 and d < bestd:
                                bestd = d
                                nxt = e
                        victim = nxt
                    if local_hits > 1:
                        self._register_hit(t, local_hits - 1)
                elif key == "sniper":
                    crit = random.random() < 0.12 + t.crit_chance + self.run.relics.get(
                        "sniper_crit", 0.0
                    )
                    amt = dmg * (1.8 if crit else 1.0)
                    if crit:
                        self.spawn_text(
                            *self.enemy_center(target), "CRIT!", (255, 255, 120)
                        )
                    t.armor_pierce = min(0.7, t.armor_pierce)
                    self.deal_damage(t, target, amt, spec)
                else:
                    self.deal_damage(t, target, dmg, spec)

    def _wrap(self, text, font, width_px):
        words = text.split()
        lines = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if font.size(test)[0] <= width_px:
                cur = test
            elif cur:
                lines.append(cur)
                cur = w
            else:
                lines.append(w)
                cur = ""
        if cur:
            lines.append(cur)
        return lines

    def dim_background(self, alpha=160):
        dim = pygame.Surface((SCREEN_W, SCREEN_H))
        dim.set_alpha(alpha)
        dim.fill(COL_DIM)
        self.screen.blit(dim, (0, 0))

    def open_upgrades(self):
        r = self.run
        if r.phase != BUILD or r.ui_mode != "none":
            return
        sel = next((t for t in r.towers if t.selected), None)
        if not sel:
            self.log("Click a tower to select, then press U.")
            return
        base_cost = self.upgrade_cost(sel)
        opts = [
            ("[1] +10% Damage", "dmg", +0.1),
            ("[2] +10% Fire Rate", "rof", +0.1),
            ("[3] +1 Range", "rng", +1),
        ]
        if sel.tkey == "poison":
            opts.append(("[4] +1 Poison Potency", "pois", +1))
        elif sel.tkey == "chain":
            opts.append(("[4] +1 Chain Bounce", "bounce", +1))
        elif sel.tkey == "sniper":
            opts.append(("[4] +5% Crit Chance", "crit", +0.05))
        r.ui_mode = "upgrade"
        r.ui_data = {"tower": sel, "cost": base_cost, "options": opts}
        self.log(f"Upgrade cost: {base_cost}. Press option key or ESC to cancel.")

    def apply_upgrade_choice(self, key_idx):
        r = self.run
        if r.ui_mode != "upgrade":
            return
        sel: Tower = r.ui_data["tower"]
        cost = r.ui_data["cost"]
        opts = r.ui_data["options"]
        if key_idx >= len(opts):
            return
        if r.coins < cost:
            self.log(f"Need {cost} coins")
            r.ui_mode = "none"
            r.ui_data.clear()
            return
        r.coins -= cost
        tag = opts[key_idx][1]
        if tag == "dmg":
            sel.dmg_mod += 0.1
            self.log("+10% damage applied")
        elif tag == "rof":
            sel.rof_mod += 0.1
            self.log("+10% fire rate applied")
        elif tag == "rng":
            sel.rng_mod += 1
            self.log("+1 range applied")
        elif tag == "pois":
            sel.poison_bonus += 1.0
            self.log("+1 poison potency")
        elif tag == "bounce":
            sel.chain_bounces += 1
            self.log("+1 chain bounce")
        elif tag == "crit":
            sel.crit_chance = min(0.5, sel.crit_chance + 0.05)
            self.log("+5% crit chance")
        r.ui_mode = "none"
        r.ui_data.clear()

    def open_unlocks(self):
        r = self.run
        if r.phase != BUILD or r.ui_mode != "none":
            return
        choices = [
            k
            for k in ["frost", "storm", "poison", "chain", "sniper"]
            if not r.unlocked.get(k, False)
        ]
        if not choices:
            self.log("All run unlocks taken.")
            return
        opts = []
        costs = []
        for k in choices:
            spec = self.specs[k]
            cost = int(spec.base_cost * 2.4)
            opts.append(f"{spec.name}  —  Cost: {cost}")
            costs.append(cost)
        r.ui_mode = "unlock"
        r.ui_data = {"choices": choices, "labels": opts, "costs": costs}
        self.log("Choose a tower to unlock (1–5) or ESC to cancel.")

    def apply_unlock_choice(self, idx):
        r = self.run
        if r.ui_mode != "unlock":
            return
        labels = r.ui_data["labels"]
        choices = r.ui_data["choices"]
        costs = r.ui_data["costs"]
        if not 0 <= idx < len(choices):
            return
        cost = costs[idx]
        key = choices[idx]
        if r.coins < cost:
            self.log(f"Need {cost} coins")
            r.ui_mode = "none"
            r.ui_data.clear()
            return
        r.coins -= cost
        r.unlocked[key] = True
        self.log(f"Unlocked {self.specs[key].name} (-{cost})")
        r.ui_mode = "none"
        r.ui_data.clear()

    def open_recap_modal(self):
        r = self.run
        towers_stats = [
            (i, t.tkey, t.level, t.dmg_done, t.shots, t.hits, t.label_idx)
            for i, t in enumerate(r.towers)
        ]
        by_type = defaultdict(lambda: {"dmg": 0.0, "shots": 0, "hits": 0, "count": 0})
        for i, key, lv, dmg, shots, hits, idx in towers_stats:
            by_type[key]["dmg"] += dmg
            by_type[key]["shots"] += shots
            by_type[key]["hits"] += hits
            by_type[key]["count"] += 1
        top_sorted = sorted(towers_stats, key=lambda e: e[3], reverse=True)[:8]
        r.ui_mode = "recap"
        r.ui_data = {
            "top": top_sorted,
            "by_type": by_type,
            "pending_relic": r.ui_data.get("pending_relic", False),
        }

    def open_relic_modal(self):
        r = self.run
        all_opts = [
            ("Runic Engravings", "global_rng", 1, "All towers +1 range"),
            ("Wind Totem", "global_rof", 0.1, "+10% fire rate (all towers)"),
            ("Battle Hymn", "global_dmg", 0.1, "+10% damage (all towers)"),
            ("Lucky Pouch", "coin_kill", 1, "+1 coin on kill"),
            ("Sacred Idol", "life", 1, "+1 life now"),
            ("Frost Sigil", "frost_slow", 0.05, "Frost slow +5%"),
            ("Static Capacitor", "chain_bounce", 1, "Chain +1 bounce"),
            ("Toxic Phials", "poison_potency", 1, "Poison +1 potency & +0.5 hit dmg"),
            ("Sharpscope", "sniper_crit", 0.05, "Sniper +5% crit chance"),
        ]
        random.shuffle(all_opts)
        picks = all_opts[:3]
        r.ui_mode = "relic"
        r.ui_data = {"relics": picks}
        self.log("Choose a relic (1–3) or ESC to skip.")

    def apply_relic_choice(self, idx):
        r = self.run
        if r.ui_mode != "relic":
            return
        relics = r.ui_data["relics"]
        if not 0 <= idx < len(relics):
            return
        name, key, val, desc = relics[idx]
        if key == "life":
            r.lives += int(val)
        else:
            r.relics[key] += val
        self.log(f"Relic taken: {name} — {desc}")
        r.ui_mode = "none"
        r.ui_data.clear()

    def draw_grid(self):
        r = self.run
        T = self.tile_size()
        for y in range(GRID_H):
            for x in range(GRID_W):
                px, py = self.grid_to_px(x, y)
                cell = r.grid[y][x]
                if cell == 1:
                    pygame.draw.rect(self.screen, COL_PATH, (px, py, T - 1, T - 1))
                elif cell == 2:
                    pygame.draw.rect(self.screen, COL_PAD, (px, py, T - 1, T - 1))
        for sx, sy in r.starts:
            px, py = self.grid_to_px(sx, sy)
            pygame.draw.rect(self.screen, COL_START, (px, py, T - 1, T - 1))
        for ex, ey in r.exits:
            px, py = self.grid_to_px(ex, ey)
            pygame.draw.rect(self.screen, COL_EXIT, (px, py, T - 1, T - 1))
        mx, my = pygame.mouse.get_pos()
        gx = (mx - MARGIN_X) // T
        gy = (my - MARGIN_Y) // T
        if 0 <= gx < GRID_W and 0 <= gy < GRID_H and (r.ui_mode == "none"):
            px, py = self.grid_to_px(gx, gy)
            has = any((t.gx == gx and t.gy == gy for t in r.towers))
            if has:
                pygame.draw.rect(
                    self.screen, COL_PREVIEW_OK, (px + 2, py + 2, T - 4, T - 4), 2
                )
            else:
                ok = (
                    r.phase == BUILD
                    and r.grid[gy][gx] == 2
                    and self.selected_tkey
                    and r.unlocked.get(self.selected_tkey, False)
                )
                pygame.draw.rect(
                    self.screen,
                    COL_PREVIEW_OK if ok else COL_PREVIEW_BAD,
                    (px + 2, py + 2, T - 4, T - 4),
                    2,
                )
            if (
                r.phase == BUILD
                and self.selected_tkey
                and r.unlocked.get(self.selected_tkey, False)
            ):
                spec = self.specs[self.selected_tkey]
                preview_rng = spec.rng + int(r.relics.get("global_rng", 0.0))
                pygame.draw.circle(
                    self.screen,
                    (200, 200, 220),
                    (px + T // 2, py + T // 2),
                    preview_rng * T,
                    1,
                )

    def draw_projectiles(self):
        for p in self.projectiles:
            progress = 1.0 - p.ttl / max(0.001, p.max_ttl)
            x = p.sx + (p.ex - p.sx) * progress
            y = p.sy + (p.ey - p.sy) * progress
            pygame.draw.line(self.screen, p.color, (p.sx, p.sy), (x, y), 2)
            pygame.draw.circle(self.screen, p.color, (int(x), int(y)), p.radius)

    def draw_towers(self):
        r = self.run
        T = self.tile_size()
        for t in r.towers:
            spec = self.specs[t.tkey]
            px, py = self.grid_to_px(t.gx, t.gy)
            pygame.draw.rect(
                self.screen,
                spec.color,
                (
                    px + max(4, T // 8),
                    py + max(4, T // 8),
                    T - max(8, T // 4),
                    T - max(8, T // 4),
                ),
            )
            code = self.short.get(t.tkey, "?")
            txt = self.font_small.render(f"{code}{t.label_idx}", True, (20, 20, 30))
            self.screen.blit(txt, (px + 6, py + 4))
            if t.selected:
                dmg, rof, rng = self.calc_stats(t)
                cx, cy = (px + T // 2, py + T // 2)
                pygame.draw.circle(self.screen, COL_TOWER_RING, (cx, cy), rng * T, 1)

    def draw_enemies(self):
        r = self.run
        T = self.tile_size()
        for e in r.enemies:
            px, py = self.grid_to_px(e.gx, e.gy)
            cx, cy = px + T // 2, py + T // 2
            margin = max(5, T // 6)
            size = T - margin * 2

            if e.boss:
                pygame.draw.rect(self.screen, COL_BOSS, (px + 4, py + 4, T - 8, T - 8))
                pygame.draw.rect(
                    self.screen, (255, 230, 120), (px + 4, py + 4, T - 8, T - 8), 2
                )
                pygame.draw.polygon(
                    self.screen,
                    (255, 235, 130),
                    [
                        (px + T // 3, py + 4),
                        (px + T // 2, py + 1),
                        (px + 2 * T // 3, py + 4),
                        (px + T // 2, py + 8),
                    ],
                )
            elif e.etype == "runner":
                col = (255, 170, 70)
                pygame.draw.polygon(
                    self.screen,
                    col,
                    [
                        (cx, py + margin),
                        (px + T - margin, py + T - margin),
                        (px + margin, py + T - margin),
                    ],
                )
            elif e.etype == "tank":
                col = (165, 105, 220)
                pygame.draw.rect(
                    self.screen,
                    col,
                    (px + margin - 2, py + margin - 2, size + 4, size + 4),
                )
                pygame.draw.rect(
                    self.screen,
                    (220, 190, 255),
                    (px + margin - 2, py + margin - 2, size + 4, size + 4),
                    2,
                )
            elif e.etype == "shield":
                col = (100, 180, 255)
                pygame.draw.polygon(
                    self.screen,
                    col,
                    [
                        (cx, py + margin),
                        (px + T - margin, cy),
                        (cx, py + T - margin),
                        (px + margin, cy),
                    ],
                )
                pygame.draw.polygon(
                    self.screen,
                    (210, 235, 255),
                    [
                        (cx, py + margin),
                        (px + T - margin, cy),
                        (cx, py + T - margin),
                        (px + margin, cy),
                    ],
                    2,
                )
            elif e.etype == "swarm":
                col = (120, 235, 130)
                small = max(3, T // 8)
                offsets = [(-small, -small), (small, -small), (0, small)]
                for ox, oy in offsets:
                    pygame.draw.circle(self.screen, col, (cx + ox, cy + oy), small)
            else:
                col = COL_ENEMY
                pygame.draw.rect(
                    self.screen, col, (px + margin, py + margin, size, size)
                )

            pygame.draw.rect(self.screen, COL_HP_BG, (px + 4, py + T - 9, T - 8, 6))
            w = int((T - 8) * max(0.0, min(1.0, e.hp / max(1.0, e.max_hp))))
            pygame.draw.rect(self.screen, COL_HP, (px + 4, py + T - 9, w, 6))

    def draw_texts(self):
        for ft in self.ftexts:
            surf = self.font_small.render(ft.text, True, ft.color)
            self.screen.blit(surf, (ft.x - surf.get_width() // 2, ft.y))

    def draw_sidebar(self):
        r = self.run
        pygame.draw.rect(
            self.screen, COL_UI, (SCREEN_W - SIDEBAR_W, 0, SIDEBAR_W, SCREEN_H)
        )
        x = SCREEN_W - SIDEBAR_W + 12
        y = 12
        wrap = SIDEBAR_W - 24
        self.screen.blit(self.font_big.render(VERSION, True, COL_TEXT), (x, y))
        y += 34
        self.screen.blit(self.font.render(f"Mode: {r.mode}", True, COL_TEXT), (x, y))
        y += 22
        self.screen.blit(
            self.font.render(f"Difficulty: {r.difficulty}", True, COL_TEXT), (x, y)
        )
        y += 22
        self.screen.blit(self.font.render(f"Wave: {r.wave}", True, COL_TEXT), (x, y))
        y += 22
        self.screen.blit(self.font.render(f"Lives: {r.lives}", True, COL_TEXT), (x, y))
        y += 22
        self.screen.blit(self.font.render(f"Coins: {r.coins}", True, COL_TEXT), (x, y))
        y += 22
        self.screen.blit(self.font.render(f"Score: {r.score}", True, COL_TEXT), (x, y))
        y += 26
        ph = "BUILD" if r.phase == BUILD else "COMBAT"
        self.screen.blit(self.font.render(f"Phase: {ph}", True, COL_TEXT), (x, y))
        y += 22
        self.screen.blit(
            self.font.render(f'Game Speed: {"2x" if r.fast else "1x"}', True, COL_TEXT),
            (x, y),
        )
        y += 26
        if self._last_log:
            for line in self._wrap(self._last_log, self.font_small, wrap):
                self.screen.blit(self.font_small.render(line, True, COL_TEXT), (x, y))
                y += 18
            y += 6
        controls = "1-7 select | T targeting | Y priority | U upgrade | R unlock | M reroll map | 0 test wave 50 | SPACE start | RMB sell | F toggle 2x | S save | ESC menu"
        for line in self._wrap(controls, self.font_small, wrap):
            self.screen.blit(self.font_small.render(line, True, COL_TEXT), (x, y))
            y += 18
        y += 6
        self.screen.blit(self.font_big.render("Towers", True, COL_TEXT), (x, y))
        y += 28
        order = ["arrow", "cannon", "frost", "storm", "poison", "chain", "sniper"]
        for i, k in enumerate(order, start=1):
            spec = self.specs[k]
            locked = not r.unlocked.get(k, False)
            label = f"[{i}] {spec.name} ${spec.base_cost}" + (
                " (LOCKED)" if locked else ""
            )
            col = (160, 160, 160) if locked else COL_TEXT
            if self.selected_tkey == k:
                label = "> " + label
            self.screen.blit(self.font_small.render(label, True, col), (x, y))
            y += 18
        sel = next((t for t in r.towers if t.selected), None)
        if self.selected_tkey and r.ui_mode == "none" and (sel is None):
            y += 10
            spec = self.specs[self.selected_tkey]
            rel = r.relics
            dmg = spec.dmg * (1.0 + rel.get("global_dmg", 0.0))
            rof = spec.rof * (1.0 + rel.get("global_rof", 0.0))
            rng = spec.rng + int(rel.get("global_rng", 0.0))
            traits = []
            if spec.splash > 0:
                traits.append(f"Splash {spec.splash}")
            if spec.slow > 0:
                traits.append(f"Slow {int(spec.slow * 100)}%")
            if spec.key == "poison":
                traits.append("Damage over time")
            if spec.key == "chain":
                traits.append("Bounces")
            if spec.key == "sniper":
                traits.append("Boss killer")
            self.screen.blit(
                self.font_big.render("Build Preview", True, COL_TEXT), (x, y)
            )
            y += 28
            self.screen.blit(
                self.font_small.render(
                    f"{spec.name} — Cost {spec.base_cost}", True, COL_TEXT
                ),
                (x, y),
            )
            y += 18
            self.screen.blit(
                self.font_small.render(
                    f"Damage: {dmg:.1f}  ROF: {rof:.2f}/s  Range: {rng}", True, COL_TEXT
                ),
                (x, y),
            )
            y += 18
            if traits:
                self.screen.blit(
                    self.font_small.render(
                        "Traits: " + ", ".join(traits), True, COL_TEXT
                    ),
                    (x, y),
                )
                y += 18
        if sel:
            y += 10
            spec = self.specs[sel.tkey]
            dmg, rof, rng = self.calc_stats(sel)
            self.screen.blit(self.font_big.render("Selected", True, COL_TEXT), (x, y))
            y += 28
            self.screen.blit(
                self.font_small.render(
                    f"{spec.name} #{sel.label_idx}  Lv{sel.level}", True, COL_TEXT
                ),
                (x, y),
            )
            y += 18
            self.screen.blit(
                self.font_small.render(
                    f"Targeting: {sel.target_mode}  |  Priority: {sel.prio}",
                    True,
                    COL_TEXT,
                ),
                (x, y),
            )
            y += 18
            self.screen.blit(
                self.font_small.render(
                    f"Damage: {dmg:.1f}  ROF: {rof:.2f}/s", True, COL_TEXT
                ),
                (x, y),
            )
            y += 18
            self.screen.blit(
                self.font_small.render(
                    f"Range: {rng}  Lifetime DMG: {sel.dmg_done:.0f} | Shots: {sel.shots} | Hits: {sel.hits}",
                    True,
                    COL_TEXT,
                ),
                (x, y),
            )
            y += 18
            if sel.tkey == "poison":
                self.screen.blit(
                    self.font_small.render(
                        f"Poison Potency: {sel.poison_bonus:.0f}", True, COL_TEXT
                    ),
                    (x, y),
                )
                y += 18
            if sel.tkey == "chain":
                self.screen.blit(
                    self.font_small.render(
                        f"Extra Bounces: {sel.chain_bounces}", True, COL_TEXT
                    ),
                    (x, y),
                )
                y += 18
            if sel.tkey == "sniper":
                self.screen.blit(
                    self.font_small.render(
                        f"Crit Chance: {int(sel.crit_chance * 100)}%", True, COL_TEXT
                    ),
                    (x, y),
                )
                y += 18
            base_cost = self.upgrade_cost(sel)
            self.screen.blit(
                self.font_small.render(f"Upgrade Cost: {base_cost}", True, COL_TEXT),
                (x, y),
            )
            y += 18
            self.screen.blit(
                self.font_small.render(
                    "U: Upgrade | T: targeting | Y: priority", True, COL_TEXT
                ),
                (x, y),
            )
            y += 18
        if r.phase == BUILD and r.ui_mode == "none":
            y += 10
            self.screen.blit(
                self.font_big.render("Next Wave Preview", True, COL_TEXT), (x, y)
            )
            y += 28
            lines, _ = self.preview_text_for_wave(r.wave)
            for line in lines:
                self.screen.blit(self.font_small.render(line, True, COL_TEXT), (x, y))
                y += 18
        if r.ui_mode == "unlock":
            self.dim_background(160)
            panel_w, panel_h = (580, 260)
            px, py = (SCREEN_W // 2 - panel_w // 2, SCREEN_H // 2 - panel_h // 2)
            pygame.draw.rect(self.screen, COL_PANEL, (px, py, panel_w, panel_h))
            pygame.draw.rect(self.screen, (90, 90, 110), (px, py, panel_w, panel_h), 2)
            title = "Unlock a Tower"
            self.screen.blit(
                self.font_big.render(title, True, COL_TEXT), (px + 16, py + 14)
            )
            oy = 60
            labels = r.ui_data.get("labels", [])
            for i, label in enumerate(labels, start=1):
                col = (
                    COL_TEXT
                    if self.run.coins >= r.ui_data["costs"][i - 1]
                    else (180, 120, 120)
                )
                self.screen.blit(
                    self.font_small.render(f"[{i}] {label}", True, col),
                    (px + 20, py + oy),
                )
                oy += 26
            self.screen.blit(
                self.font_small.render(
                    "Press 1–5 to unlock, ESC to cancel.", True, COL_TEXT
                ),
                (px + 16, py + panel_h - 32),
            )
        if r.ui_mode == "recap":
            self.dim_background(160)
            panel_w, panel_h = (820, 440)
            px, py = (SCREEN_W // 2 - panel_w // 2, SCREEN_H // 2 - panel_h // 2)
            pygame.draw.rect(self.screen, COL_PANEL, (px, py, panel_w, panel_h))
            pygame.draw.rect(self.screen, (90, 90, 110), (px, py, panel_w, panel_h), 2)
            self.screen.blit(
                self.font_big.render("Wave Recap", True, COL_TEXT), (px + 16, py + 14)
            )
            oy = 60
            self.screen.blit(
                self.font.render("Top Towers (by damage)", True, COL_TEXT),
                (px + 16, py + oy),
            )
            oy += 26
            headers = ["#", "ID", "Type", "Lvl", "Damage", "Shots", "Hits"]
            cols = [30, 70, 160, 50, 120, 100, 100]
            xoffs = [px + 16]
            for c in cols[:-1]:
                xoffs.append(xoffs[-1] + c)
            for h, xx in zip(headers, xoffs):
                self.screen.blit(
                    self.font_small.render(h, True, COL_TEXT), (xx, py + oy)
                )
            oy += 22
            top = r.ui_data.get("top", [])
            for rank, entry in enumerate(top, start=1):
                _, key, lv, dmg, shots, hits, idx = entry
                vals = [
                    str(rank),
                    f"{self.short.get(key, '?')}{idx}",
                    self.specs[key].name,
                    f"{lv}",
                    f"{int(dmg)}",
                    f"{shots}",
                    f"{hits}",
                ]
                for v, xx in zip(vals, xoffs):
                    self.screen.blit(
                        self.font_small.render(v, True, COL_TEXT), (xx, py + oy)
                    )
                oy += 20
            oy += 16
            self.screen.blit(
                self.font.render("Per-Type Totals", True, COL_TEXT), (px + 16, py + oy)
            )
            oy += 26
            headers2 = ["Type", "Count", "Damage", "Shots", "Hits"]
            cols2 = [220, 80, 140, 120, 120]
            x2 = [px + 16]
            for c in cols2[:-1]:
                x2.append(x2[-1] + c)
            for h, xx in zip(headers2, x2):
                self.screen.blit(
                    self.font_small.render(h, True, COL_TEXT), (xx, py + oy)
                )
            oy += 22
            by_type = r.ui_data.get("by_type", {})
            for key, agg in by_type.items():
                vals = [
                    self.specs[key].name,
                    f"{agg['count']}",
                    f"{int(agg['dmg'])}",
                    f"{agg['shots']}",
                    f"{agg['hits']}",
                ]
                for v, xx in zip(vals, x2):
                    self.screen.blit(
                        self.font_small.render(v, True, COL_TEXT), (xx, py + oy)
                    )
                oy += 20
            hint = "Press ENTER or ESC to close"
            if r.ui_data.get("pending_relic", False):
                hint += " — then choose a Relic"
            self.screen.blit(
                self.font_small.render(hint, True, COL_TEXT),
                (px + 16, py + panel_h - 32),
            )
        if r.ui_mode == "relic":
            self.dim_background(160)
            panel_w, panel_h = (700, 280)
            px, py = (SCREEN_W // 2 - panel_w // 2, SCREEN_H // 2 - panel_h // 2)
            pygame.draw.rect(self.screen, COL_PANEL, (px, py, panel_w, panel_h))
            pygame.draw.rect(self.screen, (90, 90, 110), (px, py, panel_w, panel_h), 2)
            self.screen.blit(
                self.font_big.render("Relic Draft", True, COL_TEXT), (px + 16, py + 14)
            )
            oy = 60
            for i, (name, key, val, desc) in enumerate(
                r.ui_data.get("relics", []), start=1
            ):
                line = f"[{i}] {name} — {desc}"
                self.screen.blit(
                    self.font_small.render(line, True, COL_TEXT), (px + 20, py + oy)
                )
                oy += 30
            self.screen.blit(
                self.font_small.render(
                    "Press 1–3 to select, or ESC to skip.", True, COL_TEXT
                ),
                (px + 16, py + panel_h - 32),
            )
        if r.ui_mode == "upgrade":
            panel_w, panel_h = (SIDEBAR_W - 24, 180)
            px, py = (SCREEN_W - SIDEBAR_W + 12, SCREEN_H - panel_h - 12)
            pygame.draw.rect(self.screen, COL_PANEL, (px, py, panel_w, panel_h))
            pygame.draw.rect(self.screen, (90, 90, 110), (px, py, panel_w, panel_h), 2)
            sel = r.ui_data.get("tower")
            opts = r.ui_data.get("options", [])
            cost = r.ui_data.get("cost", 0)
            title = (
                f"Upgrade {self.specs[sel.tkey].name} #{sel.label_idx} — Cost {cost}"
            )
            self.screen.blit(
                self.font_small.render(title, True, COL_TEXT), (px + 12, py + 12)
            )
            oy = 36
            for opt in opts:
                line = opt[0]
                self.screen.blit(
                    self.font_small.render(line, True, COL_TEXT), (px + 16, py + oy)
                )
                oy += 22
            self.screen.blit(
                self.font_small.render(
                    "Press 1/2/3/4 to apply, ESC to cancel", True, COL_TEXT
                ),
                (px + 12, py + panel_h - 28),
            )

    def draw_menu(self):
        self.screen.fill(COL_BG)
        cx, cy = (SCREEN_W // 2, SCREEN_H // 2)
        items = [
            "New Game",
            "Continue" if self.run else "Continue (no save)",
            "Leaderboards",
            "Quit",
        ]
        for i, it in enumerate(items):
            col = (120, 180, 255) if i == self.menu_sel else COL_TEXT
            self.screen.blit(
                self.font_big.render(it, True, col), (cx - 200, cy - 60 + i * 44)
            )
        mode = ALL_MODES[self.mode_sel]
        self.screen.blit(
            self.font.render(f"Mode: {mode} (←/→)", True, COL_TEXT),
            (cx - 120, cy - 140),
        )
        diff = DIFFICULTIES[self.diff_sel]
        self.screen.blit(
            self.font.render(f"Difficulty: {diff} (press D)", True, COL_TEXT),
            (cx - 160, cy - 100),
        )

    def draw_leaderboards(self):
        self.screen.fill(COL_BG)
        cx, cy = (SCREEN_W // 2, 120)
        self.screen.blit(
            self.font_big.render("Leaderboards", True, COL_TEXT), (cx - 140, 40)
        )
        for m in ALL_MODES:
            self.screen.blit(self.font_big.render(m, True, COL_TEXT), (80, cy - 24))
            board = self.get_board(m)
            for i, e in enumerate(board[:10]):
                line = f"{i + 1:2d}. {e['name'][:12]:12s} — Wave {e['score']}"
                self.screen.blit(
                    self.font.render(line, True, COL_TEXT), (100, cy + i * 22)
                )
            cy += 260
        self.screen.blit(
            self.font.render("ESC to return", True, COL_TEXT), (40, SCREEN_H - 40)
        )

    def draw_name_entry(self):
        self.screen.fill(COL_BG)
        cx, cy = (SCREEN_W // 2, SCREEN_H // 2)
        self.screen.blit(
            self.font_big.render("Game Over!", True, COL_TEXT), (cx - 100, cy - 140)
        )
        self.screen.blit(
            self.font.render(f"You reached Wave {self.run.wave}", True, COL_TEXT),
            (cx - 120, cy - 100),
        )
        self.screen.blit(
            self.font.render("Enter your name:", True, COL_TEXT), (cx - 120, cy - 40)
        )
        self.screen.blit(
            self.font_big.render(self.run.name_entry, True, (120, 180, 255)),
            (cx - 120, cy),
        )
        self.screen.blit(
            self.font.render("Press ENTER to submit", True, COL_TEXT),
            (cx - 120, cy + 40),
        )

    def handle_menu_event(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_UP:
                self.menu_sel = (self.menu_sel - 1) % 4
            elif ev.key == pygame.K_DOWN:
                self.menu_sel = (self.menu_sel + 1) % 4
            elif ev.key == pygame.K_LEFT and self.menu_sel == 0:
                self.mode_sel = (self.mode_sel - 1) % len(ALL_MODES)
            elif ev.key == pygame.K_RIGHT and self.menu_sel == 0:
                self.mode_sel = (self.mode_sel + 1) % len(ALL_MODES)
            elif ev.key == pygame.K_d:
                self.diff_sel = (self.diff_sel + 1) % len(DIFFICULTIES)
            elif ev.key == pygame.K_RETURN:
                if self.menu_sel == 0:
                    self.new_run(ALL_MODES[self.mode_sel])
                elif self.menu_sel == 1 and self.run:
                    self.continue_run()
                elif self.menu_sel == 2:
                    self.state = "leaderboard"
                elif self.menu_sel == 3:
                    self.running = False

    def handle_leader_event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.state = "menu"

    def handle_name_event(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_RETURN:
                name = self.run.name_entry.strip() or "Anonymous"
                self.add_leader(self.run.mode, name, self.run.wave)
                self.clear_save()
                self.run = None
                self.state = "menu"
            elif ev.key == pygame.K_BACKSPACE:
                self.run.name_entry = self.run.name_entry[:-1]
            else:
                ch = ev.unicode
                if ch.isprintable() and len(self.run.name_entry) < 18:
                    self.run.name_entry += ch

    def handle_game_event(self, ev):
        r = self.run
        if ev.type == pygame.KEYDOWN:
            if r.ui_mode == "upgrade":
                if ev.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                    r.ui_mode = "none"
                    r.ui_data.clear()
                    self.log("Upgrade canceled.")
                elif ev.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
                    idx = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2, pygame.K_4: 3}[
                        ev.key
                    ]
                    self.apply_upgrade_choice(idx)
                return
            if r.ui_mode == "unlock":
                if ev.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                    r.ui_mode = "none"
                    r.ui_data.clear()
                    self.log("Unlock canceled.")
                elif ev.key in (
                    pygame.K_1,
                    pygame.K_2,
                    pygame.K_3,
                    pygame.K_4,
                    pygame.K_5,
                ):
                    key_to_idx = {
                        pygame.K_1: 0,
                        pygame.K_2: 1,
                        pygame.K_3: 2,
                        pygame.K_4: 3,
                        pygame.K_5: 4,
                    }
                    idx = key_to_idx.get(ev.key, -1)
                    if idx != -1:
                        self.apply_unlock_choice(idx)
                return
            if r.ui_mode == "recap":
                if ev.key in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_SPACE):
                    pending = r.ui_data.get("pending_relic", False)
                    r.ui_mode = "none"
                    r.ui_data.clear()
                    self.log("Recap closed.")
                    if pending:
                        self.open_relic_modal()
                return
            if r.ui_mode == "relic":
                if ev.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                    idx = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2}[ev.key]
                    self.apply_relic_choice(idx)
                    return
                if ev.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                    r.ui_mode = "none"
                    r.ui_data.clear()
                    self.log("Relic skipped.")
                    return
                return
            if ev.key == pygame.K_ESCAPE:
                self.save_run()
                self.state = "menu"
            elif ev.key == pygame.K_SPACE and r.phase == BUILD:
                self.start_wave()
            elif ev.key == pygame.K_f:
                r.fast = not r.fast
                self.log(f"Speed {('2x' if r.fast else '1x')}")
            elif ev.key == pygame.K_s:
                self.save_run()
                self.log("Saved.")
            elif ev.key == pygame.K_m and r.phase == BUILD:
                grid, starts, exits = self.new_map(r.mode)
                r.grid = grid
                r.starts = starts
                r.exits = exits
                r.towers.clear()
                r.enemies.clear()
                self.log("Map rerolled.")
            elif ev.key == pygame.K_0 and r.phase == BUILD:
                r.wave = 50
                r.enemies.clear()
                r.spawn_groups.clear()
                r.wave_clear_at = 0.0
                self.log("Test mode: jumped to wave 50. Press SPACE to start.")
            elif ev.key in (
                pygame.K_1,
                pygame.K_2,
                pygame.K_3,
                pygame.K_4,
                pygame.K_5,
                pygame.K_6,
                pygame.K_7,
            ):
                idx = {
                    pygame.K_1: 0,
                    pygame.K_2: 1,
                    pygame.K_3: 2,
                    pygame.K_4: 3,
                    pygame.K_5: 4,
                    pygame.K_6: 5,
                    pygame.K_7: 6,
                }[ev.key]
                order = [
                    "arrow",
                    "cannon",
                    "frost",
                    "storm",
                    "poison",
                    "chain",
                    "sniper",
                ]
                if r.unlocked.get(order[idx], False):
                    self.selected_tkey = order[idx]
                    self.log(f"Selected {self.specs[self.selected_tkey].name}")
            elif ev.key == pygame.K_u:
                self.open_upgrades()
            elif ev.key == pygame.K_r:
                self.open_unlocks()
            elif ev.key == pygame.K_t:
                sel = next((t for t in r.towers if t.selected), None)
                if sel:
                    modes = ["First", "Last", "Strongest", "Closest"]
                    i = (modes.index(sel.target_mode) + 1) % len(modes)
                    sel.target_mode = modes[i]
                    self.log(f"Targeting → {sel.target_mode}")
            elif ev.key == pygame.K_y:
                sel = next((t for t in r.towers if t.selected), None)
                if sel:
                    prios = ["None", "Boss", "Fast", "Armored", "Swarm"]
                    i = (prios.index(sel.prio) + 1) % len(prios)
                    sel.prio = prios[i]
                    self.log(f"Priority → {sel.prio}")
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            T = self.tile_size()
            mx, my = pygame.mouse.get_pos()
            gx = (mx - MARGIN_X) // T
            gy = (my - MARGIN_Y) // T
            if 0 <= gx < GRID_W and 0 <= gy < GRID_H:
                if ev.button == 1:
                    self.place_tower(gx, gy)
                elif ev.button == 3:
                    self.sell_tower(gx, gy)

    def update_game(self, dt):
        r = self.run
        mult = 2.0 if r.fast else 1.0
        if r.phase == COMBAT and r.ui_mode == "none":
            self.tick_towers(dt * mult)
            self.tick_enemies(dt * mult)
        for ft in self.ftexts[:]:
            ft.ttl -= dt
            ft.y += ft.vy * dt
            if ft.ttl <= 0:
                self.ftexts.remove(ft)
        for p in self.projectiles[:]:
            p.ttl -= dt
            if p.ttl <= 0:
                self.projectiles.remove(p)

    def draw_game(self):
        self.screen.fill(COL_BG)
        self.draw_grid()
        self.draw_projectiles()
        self.draw_towers()
        self.draw_enemies()
        self.draw_texts()
        self.draw_sidebar()

    def run_loop(self):
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.save_run()
                    self.running = False
                if self.state == "menu":
                    self.handle_menu_event(ev)
                elif self.state == "leaderboard":
                    self.handle_leader_event(ev)
                elif self.state == "name_entry":
                    self.handle_name_event(ev)
                elif self.state == "game":
                    self.handle_game_event(ev)
            if self.state == "menu":
                self.draw_menu()
            elif self.state == "leaderboard":
                self.draw_leaderboards()
            elif self.state == "name_entry":
                self.draw_name_entry()
            elif self.state == "game":
                self.update_game(dt)
                self.draw_game()
            pygame.display.flip()
        pygame.quit()


def main():
    RogueTD().run_loop()


if __name__ == "__main__":
    main()
