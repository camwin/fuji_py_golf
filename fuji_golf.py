import os
import sys
import pygame
import math
import random
import socket
import threading
import json
import time
import uuid

# --- Window Setup ---
WIDTH, HEIGHT = 1280, 720 
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption("Meigs Field Golf Course")

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

try:
    pygame.display.set_icon(pygame.image.load(get_resource_path("icon.ico")))
except Exception:
    pass

clock = pygame.time.Clock()
font_large = pygame.font.SysFont("Verdana", 42, bold=True)
font_med = pygame.font.SysFont("Verdana", 24, bold=True)
font_small = pygame.font.SysFont("Verdana", 16, bold=True)

# --- Colors ---
ROUGH = (15, 60, 15)
FAIRWAY = (40, 130, 40)
GREEN_COLOR = (50, 170, 50)
SKY = (135, 206, 235)
WHITE = (255, 255, 255)
HOLE_COLOR = (10, 10, 10)
RED = (200, 0, 0)
YELLOW = (255, 255, 0)
GRAY = (60, 60, 60)
BROWN = (101, 67, 33)

# --- Club Data ---
CLUBS = [
    ["Driver", 265, 25, 10.0], ["3 Wood", 240, 30, 15.0], ["5 Wood", 220, 35, 18.0],
    ["3 Iron", 205, 40, 21.0], ["4 Iron", 195, 45, 24.0], ["5 Iron", 185, 50, 27.0],
    ["6 Iron", 175, 55, 30.0], ["7 Iron", 165, 60, 34.0], ["8 Iron", 155, 65, 38.0],
    ["9 Iron", 145, 70, 42.0], ["PW", 125, 80, 46.0], ["GW", 110, 90, 50.0],
    ["SW", 95, 100, 54.0], ["LW", 75, 110, 60.0]
]

PPU = 28.0 # Pixels Per Yard for 2D View
cam_z_global = 0.0

# --- P2P Networking (IPv6 + Mesh Gossip Discovery) ---
class P2PNetwork:
    def __init__(self, port=50505, player_id=None):
        self.player_id = player_id.strip() if player_id and player_id.strip() else str(uuid.uuid4())[:6]
        self.port = port
        self.peers = {}  # Keyed by player_id instead of IP address
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            if hasattr(socket, 'SO_REUSEPORT'):
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception as e:
            print(f"[P2P] Socket options error: {e}")
            
        try:
            self.sock.bind(('0.0.0.0', port))
            print(f"[P2P] Bound to port {port} successfully. Player ID: {self.player_id}")
        except Exception as e:
            print(f"[P2P] Failed to bind to port {port}: {e}")
            
        self.sock.setblocking(False)
        
        self.running = True
        self.listen_thread = threading.Thread(target=self._listen, daemon=True)
        self.listen_thread.start()

    def _listen(self):
        print("[P2P] Listening for peers...")
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                msg = json.loads(data.decode('utf-8'))
                
                if msg['type'] == 'state' and msg['id'] != self.player_id:
                    p_id = msg['id']
                    if p_id not in self.peers:
                        print(f"[P2P] Receiving state from new peer: {p_id} at {addr}")
                    self.peers[p_id] = {'state': msg['data'], 'last_seen': time.time()}
                        
            except (BlockingIOError, OSError):
                time.sleep(0.01)
            except Exception as e:
                print(f"[P2P] Listen error: {e}")
                time.sleep(0.01)

    def broadcast_state(self, state_dict):
        msg = {'type': 'state', 'id': self.player_id, 'data': state_dict}
        data = json.dumps(msg).encode('utf-8')
        try: 
            self.sock.sendto(data, ('255.255.255.255', self.port))
        except Exception: pass

    def get_active_peers(self):
        now = time.time()
        self.peers = {p_id: p for p_id, p in self.peers.items() if now - p['last_seen'] <= 5}
        return [(p_id, p['state']) for p_id, p in self.peers.items()]

def calculate_trackman_stats(club_idx, trajectory_offset, power_mult=1.0):
    base_loft = CLUBS[club_idx][3]
    base_aoa = -(base_loft / 8.0) + 3.0
    
    dynamic_loft = base_loft + trajectory_offset
    aoa = base_aoa + (trajectory_offset * 0.5)
    
    launch_angle = dynamic_loft * 0.85 + aoa * 0.15
    spin_loft = dynamic_loft - aoa
    
    # Trackman physics: Spin peaks around 45 degrees of spin loft.
    if spin_loft <= 45:
        effective_spin_loft = spin_loft
    else:
        effective_spin_loft = 45 - (spin_loft - 45) * 0.8
        
    rpm = max(500, int(effective_spin_loft * 240 * power_mult))
    return dynamic_loft, launch_angle, spin_loft, rpm

def apply_wind_physics(base_dist, base_height, aim_angle, wx, wy, rpm):
    rad = math.radians(aim_angle)
    shot_dx = math.sin(rad)
    shot_dy = math.cos(rad)
    
    # Calculate tailwind (positive means wind is blowing with the shot)
    tailwind = wx * shot_dx + wy * shot_dy
    headwind = -tailwind
    
    # Crosswind vector (perpendicular to shot)
    cross_dx = math.cos(rad)
    cross_dy = -math.sin(rad)
    crosswind_mag = wx * cross_dx + wy * cross_dy
    
    # High spin violently magnifies the lifting effect of a headwind (ballooning)
    spin_factor = rpm / 3000.0
    
    if headwind > 0:
        dist_mult = 1.0 - (headwind * 0.005) - (headwind * spin_factor * 0.004)
        height_mult = 1.0 + (headwind * 0.005) + (headwind * spin_factor * 0.006)
    else:
        # Tailwind knocks the ball down slightly and carries it
        dist_mult = 1.0 - (headwind * 0.006) 
        height_mult = 1.0 + (headwind * 0.004)
        
    # Return adjusted flight stats and the pure lateral crosswind components
    return max(0.1, base_dist * dist_mult), max(0.1, base_height * height_mult), crosswind_mag * cross_dx, crosswind_mag * cross_dy

class Course:
    def __init__(self, name, seed):
        self.name = name
        self.seed = seed
        self.theme = "City"
        
        # Determine expected theme for built-in courses
        expected_theme = None
        if self.name.startswith("Meigs Field"): expected_theme = "City"
        elif self.name.startswith("Augusta National"): expected_theme = "Augusta"
        elif self.name.startswith("Central Park"): expected_theme = "NYC"
        elif self.name.startswith("Augusta Pines"): expected_theme = "Forest"
        elif self.name.startswith("Mirage Dunes"): expected_theme = "Desert"
        
        loaded_from_json = False
        # Attempt to load from JSON first
        json_path = os.path.join(get_resource_path("courses"), f"{name.replace(' ', '_')}.json")
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                try:
                    data = json.load(f)
                    self.theme = data.get("theme", "City")
                    if expected_theme and self.theme != expected_theme:
                        pass # Regenerate if outdated JSON theme doesn't match
                    else:
                        if data.get("holes") and "pin_positions" not in data["holes"][0]:
                            pass # Force regeneration to include the new pin positions update!
                        self.skyline = data.get("skyline", [])
                        self.holes = data.get("holes", [])
                        loaded_from_json = True
                except Exception:
                    pass
                    
        if not loaded_from_json:
            self.skyline = self._generate_skyline()
            self.holes = self._generate_holes()
            
            # Auto-export newly generated courses to JSON to allow static editing!
            try:
                os.makedirs(get_resource_path("courses"), exist_ok=True)
                with open(json_path, 'w') as f:
                    json.dump({"theme": self.theme, "skyline": self.skyline, "holes": self.holes}, f, indent=4)
            except Exception as e:
                print(f"Could not save course JSON: {e}")
                
        if self.theme == "Desert":
            self.rough_color = (200, 170, 130)  # Sand color
        else:
            self.rough_color = ROUGH

    def _generate_skyline(self):
        elements = []
        random.seed(self.seed)

        themes = ["Desert", "Forest", "NYC", "City", "Augusta"]
        
        if self.name.startswith("Meigs Field"):
            self.theme = "City"
        elif self.name.startswith("Central Park"):
            self.theme = "NYC"
        elif self.name.startswith("Augusta Pines"):
            self.theme = "Forest"
        elif self.name.startswith("Mirage Dunes"):
            self.theme = "Desert"
        elif self.name.startswith("Augusta National"):
            self.theme = "Augusta"
        else:
            self.theme = random.choice(themes)

        if self.theme == "City":
            for _ in range(70):
                color = random.choice([(70,75,80), (80,85,90), (60,65,70)])
                elements.append(("rect", random.uniform(190, 350), random.uniform(1.0, 3.0), random.uniform(30, 90), color))
            for _ in range(50):
                color = random.choice([(40,40,40), (30,35,40), (20,25,30), (50,50,60)])
                elements.append(("rect", random.uniform(190, 350), random.uniform(1.5, 4.0), random.uniform(50, 150), color))
            if self.name.startswith("Meigs Field"):
                elements.append(("rect", 270, 4.5, 260, (15, 15, 15), "SEARS"))
                elements.append(("rect", 300, 3.5, 230, (25, 25, 25), "HANCOCK"))
                elements.append(("rect", 285, 3.5, 210, (220, 220, 220), "AON"))
        elif self.theme == "NYC":
            # Add trees for Central Park foreground
            for _ in range(360):
                color = random.choice([(20, 60, 25), (15, 50, 20), (25, 65, 30)])
                elements.append(("tree", random.uniform(0, 360), random.uniform(4, 10), random.uniform(60, 130), color))
            # Dense wall of mid-level buildings
            for _ in range(400):
                color = random.choice([(60,65,70), (50,55,60), (40,45,50)])
                elements.append(("rect", random.uniform(0, 360), random.uniform(1.5, 3.5), random.uniform(60, 160), color))
            # Taller skyscrapers all around
            for _ in range(200):
                color = random.choice([(30,35,40), (20,25,30), (15,20,25)])
                elements.append(("rect", random.uniform(0, 360), random.uniform(2.5, 6.0), random.uniform(120, 280), color))
            if self.name.startswith("Central Park"):
                elements.append(("rect", 250, 4.0, 320, (50, 50, 55), "EMPIRE"))
                elements.append(("rect", 280, 3.0, 280, (70, 75, 80), "CHRYSLER"))
                # Twin Towers
                elements.append(("rect", 180, 4.0, 350, (65, 70, 75), "WTC1"))
                elements.append(("rect", 185, 4.0, 350, (65, 70, 75), "WTC2"))
            # Add a few extra landmark-sized buildings in other directions
            elements.append(("rect", 45, 4.5, 300, (45, 50, 55), "TOWER_N")) # Example landmark
            elements.append(("rect", 135, 5.0, 340, (55, 60, 65), "TOWER_E")) # Example landmark
            elements.append(("rect", 315, 4.2, 290, (40, 40, 45), "TOWER_W")) # Example landmark
        elif self.theme == "Desert":
            for _ in range(40):
                color = random.choice([(180, 120, 80), (160, 100, 70), (140, 90, 60)])
                elements.append(("mountain", random.uniform(0, 360), random.uniform(15, 40), random.uniform(40, 120), color))
        elif self.theme == "Forest":
            for _ in range(120):
                color = random.choice([(20, 60, 25), (15, 50, 20), (25, 65, 30)])
                elements.append(("tree", random.uniform(0, 360), random.uniform(3, 8), random.uniform(60, 130), color))
            for _ in range(60):
                color = random.choice([(15, 50, 20), (10, 45, 15)])
                elements.append(("tree", random.uniform(0, 360), random.uniform(4, 10), random.uniform(100, 180), color))
        elif self.theme == "Augusta":
            # Augusta skyline: dense, dark green trees and some distant low hills
            for _ in range(120):
                color = random.choice([(20, 60, 25), (15, 50, 20), (25, 65, 30)])
                elements.append(("tree", random.uniform(0, 360), random.uniform(3, 8), random.uniform(60, 130), color))
            for _ in range(60):
                color = random.choice([(15, 50, 20), (10, 45, 15)])
                elements.append(("tree", random.uniform(0, 360), random.uniform(4, 10), random.uniform(100, 180), color))
                
            for _ in range(30): # Distant hills
                color = random.choice([(80, 90, 80), (70, 80, 70)])
                elements.append(("mountain", random.uniform(0, 360), random.uniform(10, 30), random.uniform(30, 80), color))
        return elements

    def _generate_holes(self):
        course = []
        # Generate 18 holes
        random.seed(self.seed)
        
        pars = [4] * 18
        par3_idx = random.sample(range(18), 4)
        for i in par3_idx: pars[i] = 3
        
        avail = [i for i in range(18) if i not in par3_idx]
        par5_idx = random.sample(avail, random.randint(2, 4))
        for i in par5_idx: pars[i] = 5
        
        palettes = {
            "City": [(30, 80, 30), (40, 90, 40), (20, 70, 20)],
            "NYC": [(30, 80, 30), (40, 90, 40), (20, 70, 20)], # Green trees in NYC, distinct from city buildings
            "Augusta": [(10, 50, 15), (8, 45, 12), (12, 55, 18)], # Darker, more solemn greens for Augusta
            "Forest": [(20, 60, 25), (15, 50, 20), (25, 65, 30), (10, 45, 15)],
            "Desert": [(60, 100, 40), (70, 110, 50), (50, 90, 30)]
        }
        palette = palettes.get(self.theme, palettes["City"])
        
        if self.name.startswith("Augusta National"):
            return self._generate_augusta_holes(palette)
            
        for i, p in enumerate(pars):
            if p == 3: dist = random.randint(150, 210)
            elif p == 4: dist = random.randint(350, 450)
            else: dist = random.randint(500, 600)

            if self.name.startswith("Meigs Field"):
                curve_opts = [2, 5, 8]  # Very easy
            elif self.name.startswith("Mirage Dunes"):
                curve_opts = [15, 20, 25]  # Medium
            elif self.name.startswith("Central Park"):
                curve_opts = [35, 45, 55]  # Hard
            else:
                curve_opts = [20, 30, 40]
                
            curve_dir = random.choice(curve_opts) if i % 2 == 0 else random.choice([-x for x in curve_opts])
            
            gw1, gh1 = random.uniform(12, 16), random.uniform(14, 18)
            gw2, gh2 = random.uniform(14, 18), random.uniform(12, 16)
            ox, oy = random.uniform(-6, 6), random.uniform(-6, 6)
            
            hole_x = curve_dir
            
            actual_hole_x = math.sin(dist*0.01)*curve_dir
            pin_positions = [
                (actual_hole_x, dist), # Center
                (actual_hole_x - gw1*0.4, dist + gh1*0.4), # Back Left
                (actual_hole_x + gw1*0.4, dist - gh1*0.4), # Front Right
                (actual_hole_x + ox + gw2*0.3, dist + oy - gh2*0.3) # Secondary Lobe
            ]
            
            fairway = []
            for y in range(-20, dist+81, 20):
                z = math.sin(y * 0.02 + i) * 6.0 if p != 3 else 0.0
                cs = math.sin(y * 0.01 + i) * 0.1 if p != 3 else 0.0
                x = math.sin(y * 1.5708 / max(1, dist)) * curve_dir
                fairway.append((y, x, random.uniform(25, 35), z, cs))
                
            green_z = math.sin(dist * 0.02 + i) * 6.0 if p != 3 else 0.0
            
            bunkers = []
            # Bunkers guarding the green
            bunkers.append((hole_x + random.choice([-28, 28]), dist + random.choice([-26, 26]), random.uniform(6, 10), green_z))
            if p > 3:
                fy = dist * random.uniform(0.5, 0.8)
                fx = math.sin(fy * 1.5708 / max(1, dist)) * curve_dir + random.choice([-20, 20])
                fz = math.sin(fy * 0.02 + i) * 6.0
                bunkers.append((fx, fy, random.uniform(6, 12), fz))
                
            water_hazards = []
            if random.random() < 0.4:
                wy = dist * random.uniform(0.3, 0.7)
                wx = math.sin(wy * 1.5708 / max(1, dist)) * curve_dir + random.choice([-30, 30])
                wr = random.uniform(15, 35)
                if dist - wy < wr + 25:
                    wy = dist - (wr + 25)
                water_hazards.append((wx, wy, wr))
                
            trees = []
            for _ in range(10 + p*6):
                ty = random.uniform(20, dist + 20)
                tx = math.sin(ty * 1.5708 / max(1, dist)) * curve_dir + random.choice([random.uniform(-60, -30), random.uniform(30, 60)])
                tz = math.sin(ty * 0.02 + i) * 6.0
                t_color = random.choice(palette)
                trees.append((tx, ty, tz, random.uniform(20, 50), random.uniform(4, 9), t_color))
                
            course.append({
                "par": p, "hole_pos": (actual_hole_x, dist), 
                "pin_positions": pin_positions,
                "fairway": fairway,
                "green": ((gw1, gh1), (gw2, gh2), (ox, oy)),
                "slope_waves": [
                    (random.uniform(0.005, 0.010), random.uniform(0.04, 0.1), random.uniform(0.04, 0.1), random.uniform(0, 6.28), random.uniform(0, 6.28)),
                    (random.uniform(0.002, 0.006), random.uniform(0.1, 0.2), random.uniform(0.1, 0.2), random.uniform(0, 6.28), random.uniform(0, 6.28))
                ],
                "green_z": green_z,
                "bunkers": bunkers,
                "water": water_hazards,
                "trees": trees
            })
        return course

    def _get_augusta_elevation(self, i, y, dist, p):
        pct = max(0.0, min(1.0, y / dist))
        
        # Dramatic, real-world elevation changes for Augusta (in yards)
        if i == 0: z = pct * 15.0
        elif i == 1: z = -pct * 30.0 # Hole 2: Pink Dogwood downhill
        elif i == 2: z = pct * 10.0
        elif i == 3: z = -pct * 15.0
        elif i == 4: z = pct * 20.0
        elif i == 5: z = -pct * 25.0
        elif i == 6: z = pct * 10.0
        elif i == 7: z = pct * 25.0
        elif i == 8: z = -math.sin(pct * 3.14) * 15.0 + (pct * 5.0) # Hole 9: Severely rolling
        elif i == 9: z = -pct * 35.0 # Hole 10: Massive drop
        elif i == 10: z = -pct * 20.0
        elif i == 11: 
            z = -pct * 15.0
            if dist - 40 < y < dist - 15:
                z -= math.sin((y - (dist - 40)) / 25.0 * 3.1415) * 4.0 # Creek dip
            elif y >= dist + 8:
                z += (y - (dist + 8)) * 0.8 # Steep backstop
        elif i == 12: z = -pct * 15.0 + math.sin(pct * 15.0) * 4.0 # Hole 13: Downhill, rolling
        elif i == 13: z = pct * 15.0
        elif i == 14: z = -pct * 20.0
        elif i == 15: z = -pct * 10.0
        elif i == 16: z = pct * 15.0
        elif i == 17: z = pct * 35.0 # Hole 18: Steeply uphill
        else: z = 0.0

        if p != 3: z += math.sin(y * 0.03 + i) * 4.5
            
        # Cross-slope factor (positive = slopes right-to-left, negative = slopes left-to-right)
        cs = 0.0
        if i == 12: cs = 0.30      # Hole 13 (Azalea) slopes severely right to left
        elif i == 9: cs = 0.15     # Hole 10 (Camellia) tilts right to left
        elif i == 1: cs = 0.10     # Hole 2 tilts right to left
        elif i == 8: cs = -0.20    # Hole 9 tilts left to right
        else: cs = math.sin(y * 0.01 + i) * 0.08
            
        return z, cs

    def _generate_augusta_holes(self, palette):
        course = []
        random.seed(self.seed)
        augusta_data = [(4, 445), (5, 575), (4, 350), (3, 240), (4, 495), (3, 180), (4, 450), (5, 570), (4, 460), (4, 495), (4, 520), (3, 155), (5, 510), (4, 440), (5, 550), (3, 170), (4, 440), (4, 465)]

        augusta_curves = {
            0: 10, 1: -35, 2: -12, 3: 0, 4: -30, 5: 0, 6: 15, 7: 8, 8: -15, 
            9: -35, 10: 25, 11: 0, 12: -50, 13: -15, 14: 15, 15: 0, 16: 10, 17: 35
        }
        
        # Specific, researched bunker layouts for Augusta National (x_offset_from_hole_center, y_offset_from_green, radius)
        bunker_layouts = {
            0: [(-32, 8, 12), (35, 160, 15)],  # 1: Greenside L, Fairway R
            1: [(-28, -14, 10), (28, -14, 10), (22, 280, 22)], # 2: Greenside front L/R, Fairway R edge
            2: [(-25, 180, 8), (-15, 170, 9), (-5, 160, 8), (5, 150, 8)], # 3: 4 Fairway bunkers left/middle
            3: [(-32, -10, 14), (32, 10, 14)], # 4: Two large front/side bunkers
            4: [(-25, 250, 18), (-25, 220, 18), (-22, -8, 12), (0, -26, 10)], # 5: Deep fairway bunkers left, 2 greenside
            5: [(-28, 22, 18)], # 6: Large front left bunker
            6: [(-38, 30, 9), (-34, -32, 9), (0, 38, 9), (34, -32, 9), (42, 24, 9)], # 7: Ring of 5 bunkers, pushed outward
            7: [(22, 250, 15)], # 8: Fairway bunker on the right
            8: [(-34, 26, 12), (-34, 0, 12), (32, 8, 10)], # 9: Two front left and right greenside
            9: [(35, 200, 25)], # 10: Large right fairway bunker
            11: [(0, 18, 10), (12, -14, 4), (20, -14, 4)], # 12: Front center, two back right
            12: [(-28, -10, 7), (-14, -14, 7), (14, -12, 7), (28, -10, 7)], # 13: Four small bunkers behind green
            15: [(32, 0, 12), (38, -26, 12), (-38, 10, 12)], # 16: Three bunkers, mostly right, pushed out
            17: [(-40, 150, 14), (-36, 180, 14), (36, 8, 16)] # 18: Two fairway L, one greenside R
        }
        
        for i, (p, dist) in enumerate(augusta_data):
            curve_dir = augusta_curves.get(i, 0)
            gw1, gh1 = random.uniform(12, 16), random.uniform(14, 18)
            gw2, gh2 = random.uniform(14, 18), random.uniform(12, 16)
            ox, oy = random.uniform(-6, 6), random.uniform(-6, 6)
            
            slope_waves = [ # Augusta greens are notoriously fast and slopey
                (random.uniform(0.010, 0.015), random.uniform(0.04, 0.1), random.uniform(0.04, 0.1), random.uniform(0, 6.28), random.uniform(0, 6.28)),
                (random.uniform(0.005, 0.010), random.uniform(0.1, 0.2), random.uniform(0.1, 0.2), random.uniform(0, 6.28), random.uniform(0, 6.28))
            ]
            
            if i == 2: # Hole 3
                gw1, gh1 = 15, 10
                gw2, gh2 = 10, 15
                ox, oy = 0, 8
                slope_waves = [ # Flattened significantly
                    (random.uniform(0.001, 0.002), random.uniform(0.04, 0.1), random.uniform(0.04, 0.1), random.uniform(0, 6.28), random.uniform(0, 6.28))
                ]
            elif i == 3: # Hole 4
                gw1, gh1 = 17, 17
                gw2, gh2 = 20, 11
                ox, oy = 0, -10
            elif i == 11: # Hole 12
                gw1, gh1 = 20, 8
                gw2, gh2 = 18, 7
                ox, oy = 16, 6
                slope_waves = [
                    (random.uniform(0.002, 0.005), 0.1, 0.1, 0, 0)
                ]
                
            hole_x = curve_dir
            if i == 12:
                hole_x = -140
                
            pin_positions = [
                (hole_x, dist),
                (hole_x - gw1*0.5, dist + gh1*0.5),
                (hole_x + gw1*0.5, dist - gh1*0.5),
                (hole_x + ox + gw2*0.4, dist + oy - gh2*0.4)
            ]
                
            fairway = []
            for y in range(-20, dist+81, 20):
                z, cs = self._get_augusta_elevation(i, y, dist, p)
                if i == 12:
                    if y <= 220:
                        x = 0
                    else:
                        x = math.sin((y - 220) * 1.5708 / max(1, dist - 220)) * hole_x
                else:
                    x = math.sin(y * 1.5708 / max(1, dist)) * curve_dir
                fairway.append((y, x, random.uniform(25, 35), z, cs))
            green_z, _ = self._get_augusta_elevation(i, dist, dist, p)
            bunkers = []
            if i in bunker_layouts:
                for b_x_off, b_y_off, b_rad in bunker_layouts[i]:
                    b_y = dist - b_y_off
                    if b_y_off > 50:
                        if i == 12:
                            if b_y <= 220:
                                b_x = b_x_off
                            else:
                                b_x = math.sin((b_y - 220) * 1.5708 / max(1, dist - 220)) * hole_x + b_x_off
                        else:
                            b_x = math.sin(b_y * 1.5708 / max(1, dist)) * curve_dir + b_x_off
                    else:
                        b_x = hole_x + b_x_off
                    b_z, _ = self._get_augusta_elevation(i, b_y, dist, p)
                    bunkers.append((b_x, b_y, b_rad, b_z))
            elif i != 13: # Fallback for unlisted holes (except 14)
                bunkers.append((hole_x + random.choice([-28, 28]), dist + random.choice([-26, 26]), random.uniform(6, 10), green_z))

            water_hazards = []
            if i == 10: water_hazards.append((hole_x - 30, dist - 30, 20))
            elif i == 11: 
                for wx in range(int(hole_x) - 60, int(hole_x) + 60, 8):
                    water_hazards.append((wx, dist - 36, 9))
            elif i == 12: 
                # Rae's Creek running along the left of the fairway and in front of the green
                for wy in range(250, int(dist) - 20, 25):
                    fx = math.sin((wy - 220) * 1.5708 / max(1, dist - 220)) * hole_x
                    water_hazards.append((fx - 25, wy, 15))
                for wx in range(int(hole_x) - 40, int(hole_x) + 40, 15):
                    water_hazards.append((wx, dist - 25, 12))
            elif i == 14: water_hazards.append((hole_x, dist - 40, 22))
            elif i == 15: water_hazards.append((hole_x - 25, dist - 35, 20))
            trees = []
            if i == 11:
                # Hogan's Bridge
                bridge_y = dist - 35
                bridge_x = hole_x - 26
                bridge_z, _ = self._get_augusta_elevation(i, bridge_y, dist, p)
                trees.append((bridge_x, bridge_y, bridge_z + 1.2, 1.8, 22, (140, 130, 120), "bridge", 75))
                
                # Flowery Azalea bushes
                for _ in range(45):
                    ay = dist + random.uniform(25, 45)
                    ax = hole_x + random.uniform(-45, 45)
                    az, _ = self._get_augusta_elevation(i, ay, dist, p)
                    color = random.choice([(180, 60, 110), (200, 80, 130), (160, 40, 100), (190, 100, 140)])
                    trees.append((ax, ay, az, random.uniform(1.5, 3.5), random.uniform(2.5, 5), color, "azalea"))
            elif i == 12:
                # Azaleas behind the green on 13
                for _ in range(30):
                    ay = dist + random.uniform(25, 60)
                    ax = hole_x + random.uniform(-60, 60)
                    az, _ = self._get_augusta_elevation(i, ay, dist, p)
                    color = random.choice([(180, 60, 110), (200, 80, 130), (160, 40, 100), (190, 100, 140)])
                    trees.append((ax, ay, az, random.uniform(1.0, 2.5), random.uniform(3, 5), color, "azalea"))

            for _ in range(15 + p*6):
                ty = random.uniform(20, dist + 20)
                if i == 12:
                    if ty <= 220:
                        tx = random.choice([random.uniform(-60, -30), random.uniform(30, 60)])
                        tz, tcs = self._get_augusta_elevation(i, ty, dist, p)
                        tz += tcs * tx
                    else:
                        fx = math.sin((ty - 220) * 1.5708 / max(1, dist - 220)) * hole_x
                        tx = fx + random.choice([random.uniform(-60, -30), random.uniform(30, 60)])
                        tz, tcs = self._get_augusta_elevation(i, ty, dist, p)
                        tz += tcs * (tx - fx)
                else:
                    tx = math.sin(ty * 1.5708 / max(1, dist)) * curve_dir + random.choice([random.uniform(-60, -30), random.uniform(30, 60)])
                    tz, tcs = self._get_augusta_elevation(i, ty, dist, p)
                    tz += tcs * (tx - math.sin(ty * 1.5708 / max(1, dist)) * curve_dir)
                t_color = random.choice(palette)
                trees.append((tx, ty, tz, random.uniform(25, 60), random.uniform(5, 10), t_color))
            course.append({
                "par": p, "hole_pos": (hole_x, dist), 
                "pin_positions": pin_positions,
                "fairway": fairway,
                "green": ((gw1, gh1), (gw2, gh2), (ox, oy)),
                "slope_waves": slope_waves,
                "green_z": green_z,
                "bunkers": bunkers,
                "water": water_hazards,
                "trees": trees
            })
        return course

def get_elevation(x, y, fairway_nodes, green_z):
    if not fairway_nodes: return 0.0
    if y <= fairway_nodes[0][0]:
        node = fairway_nodes[0]
        cs = node[4] if len(node) > 4 else 0.0
        return node[3] + cs * (x - node[1])
        if y >= fairway_nodes[-1][0]:
            node = fairway_nodes[-1]
            cs = node[4] if len(node) > 4 else 0.0
            return node[3] + cs * (x - node[1])
    for i in range(len(fairway_nodes)-1):
        if fairway_nodes[i][0] <= y <= fairway_nodes[i+1][0]:
            node1, node2 = fairway_nodes[i], fairway_nodes[i+1]
            t = (y - node1[0]) / (node2[0] - node1[0])
            
            cs1 = node1[4] if len(node1) > 4 else 0.0
            z1 = node1[3] + cs1 * (x - node1[1])
            cs2 = node2[4] if len(node2) > 4 else 0.0
            z2 = node2[3] + cs2 * (x - node2[1])
            return z1 + t * (z2 - z1)
    return 0.0

def get_slope_at_point(x, y, fairway_nodes, green_z):
    h = 0.5 # A slightly larger step is more stable for this terrain
    z_center = get_elevation(x, y, fairway_nodes, green_z)
    z_plus_x = get_elevation(x + h, y, fairway_nodes, green_z)
    z_plus_y = get_elevation(x, y + h, fairway_nodes, green_z)
    
    # Gradient points uphill, so slope is the rate of change
    slope_x = (z_plus_x - z_center) / h
    slope_y = (z_plus_y - z_center) / h
    return slope_x, slope_y

def get_slope(x, y, waves, pin_positions):
    sx, sy = 0.0, 0.0
    for amp, fx, fy, px, py in waves:
        sx += math.cos(x * fx + px) * amp
        sy += math.sin(y * fy + py) * amp
        
    # Flatten the green near ALL pin positions to create flat zones
    min_dist = 9999.0
    for px, py in pin_positions:
        dist = math.hypot(x - px, y - py)
        if dist < min_dist:
            min_dist = dist
            
    attenuation = min(1.0, min_dist / 6.0)
    return sx * attenuation, sy * attenuation

def is_on_green(bx, by, green_center, green_shape):
    g1_w, g1_h = green_shape[0]
    g2_w, g2_h = green_shape[1]
    ox, oy = green_shape[2]
    
    dx1, dy1 = bx - green_center[0], by - green_center[1]
    if (dx1**2 / g1_w**2) + (dy1**2 / g1_h**2) <= 1: return True
    
    dx2, dy2 = bx - (green_center[0] + ox), by - (green_center[1] + oy)
    if (dx2**2 / g2_w**2) + (dy2**2 / g2_h**2) <= 1: return True
    return False

def is_in_chipping_range(bx, by, green_center, green_shape, buffer_yards=4):
    g1_w, g1_h = green_shape[0]
    g2_w, g2_h = green_shape[1]
    ox, oy = green_shape[2]
    
    dx1, dy1 = bx - green_center[0], by - green_center[1]
    if (dx1**2 / (g1_w + buffer_yards)**2) + (dy1**2 / (g1_h + buffer_yards)**2) <= 1: return True
    
    dx2, dy2 = bx - (green_center[0] + ox), by - (green_center[1] + oy)
    if (dx2**2 / (g2_w + buffer_yards)**2) + (dy2**2 / (g2_h + buffer_yards)**2) <= 1: return True
    return False

class Ball:
    def __init__(self):
        self.x, self.y, self.z = 0, 0, 0
        self.vx, self.vy = 0, 0
        self.strokes = 0
        self.is_moving = False
        self.flight_progress = 0
        self.flight_duration = 100
        self.max_height = 0
        self.wind_x, self.wind_y = 0, 0
        
        self.rpm = 0
        self.loft_offset = 0.0
        self.dynamic_loft = 0.0
        self.launch_angle = 0.0
        self.spin_loft = 0.0
        self.dist = 0
        self.height = 0
        self.angle = 0
        self.bounce_count = 0
        self.start_z = 0.0
        self.elev_diff = 0.0
        
        self.prev_x, self.prev_y = 0, 0
        self.lie = 100
        # Putting state
        self.putt_x = 0
        self.putt_y = 0
        self.putt_vx = 0
        self.putt_vy = 0
        self.putt_z = 0
        self.putt_vz = 0
        self.chipping = False
        self.ds = None # Drag start
        self.is_dragging = False
        self.curve_accel_x = 0.0
        self.curve_accel_y = 0.0
        self.hit_tree = False

    def start_flight(self, dist, height, angle, wx, wy, power_mult, loft_offset, club_idx, face_angle, fairway_nodes, green_z):
        self.prev_x, self.prev_y = self.x, self.y
        self.is_moving = True
        self.flight_progress = 0
        self.bounce_count = 0
        self.loft_offset = loft_offset
        self.hit_tree = False
        
        d_loft, l_angle, s_loft, self.rpm = calculate_trackman_stats(club_idx, loft_offset, power_mult)
        self.dynamic_loft = d_loft
        self.launch_angle = l_angle
        self.spin_loft = s_loft

        # 9 Ball Flight Laws: Initial direction is mostly face angle (85%) + club path (15%)
        start_angle = angle + (face_angle * 0.85)
        spin_axis = face_angle * 4.0
        spin_eff = math.cos(math.radians(spin_axis))

        rad = math.radians(start_angle)
        # Spin axis tilt reduces carry distance slightly (glancing blow inefficiency)
        actual_dist = (dist * power_mult) * random.uniform(0.98, 1.02) * max(0.7, spin_eff)
        base_height = height * power_mult
        
        # Apply Aerodynamic Wind & Spin calculations
        adj_dist, adj_height, lat_wx, lat_wy = apply_wind_physics(actual_dist, base_height, start_angle, wx, wy, self.rpm)
        
        # Adjust for elevation difference (Uphill plays longer, downhill plays shorter)
        start_elev = get_elevation(self.x, self.y, fairway_nodes, green_z)
        self.start_z = start_elev
        target_x_est = self.x + adj_dist * math.sin(math.radians(start_angle))
        target_y_est = self.y + adj_dist * math.cos(math.radians(start_angle))
        target_elev = get_elevation(target_x_est, target_y_est, fairway_nodes, green_z)
        self.elev_diff = target_elev - start_elev
        
        adj_dist -= self.elev_diff * 1.0 # ~1 yard adjustment per 1 yard of elevation
        adj_dist = max(0.1, adj_dist)
        
        self.dist = adj_dist
        self.height = adj_height
        self.angle = start_angle
        self.flight_duration = 100
        
        self.vy = (self.dist / self.flight_duration) * math.cos(rad)
        self.vx = (self.dist / self.flight_duration) * math.sin(rad)
        self.max_height = self.height
        
        # Curve acceleration based on spin axis (face to path difference)
        self.curve_accel_x = math.cos(rad) * face_angle * 0.001 * (self.rpm / 2000.0)
        self.curve_accel_y = -math.sin(rad) * face_angle * 0.001 * (self.rpm / 2000.0)

        self.wind_x, self.wind_y = lat_wx / 60.0, lat_wy / 60.0
        self.strokes += 1

    def start_bounce(self, fairway_nodes, green_z, bunkers):
        self.bounce_count += 1
        self.flight_progress = 0
        self.hit_tree = False
        
        in_bunker = any(math.hypot(self.x - bx, self.y - by) < br for bx, by, br, _ in bunkers)
        
        if in_bunker:
            # Sand realistically grabs the ball and kills momentum
            dist_damp = random.uniform(0.01, 0.04)
            height_damp = random.uniform(0.02, 0.08)
            self.rpm = int(self.rpm * 0.1) # Kills spin immediately
        else:
            # High RPM reduces forward bounce or causes backspin
            # Adjusted to be more realistic (max ~4% backspin instead of 15%)
            spin_effect = (self.rpm - 2500) / 30000.0
            dist_damp = 0.15 - spin_effect
            dist_damp = max(-0.04, min(0.25, dist_damp))
            
            height_damp = 0.2 + (self.loft_offset / 120.0)
            height_damp = max(0.1, min(0.3, height_damp))
            self.rpm = int(self.rpm * 0.5) # Spin decays after hitting the ground
        
        self.dist *= dist_damp
        self.height *= height_damp
        old_flight_duration = self.flight_duration
        self.flight_duration = max(5, int(self.flight_duration * 0.6))
        
        if self.flight_duration <= 5 or self.height < 0.5:
            self.is_moving = False
            self.z = 0
        else:
            # Dampen velocity first
            dampened_vx = self.vx * dist_damp * (old_flight_duration / self.flight_duration)
            dampened_vy = self.vy * dist_damp * (old_flight_duration / self.flight_duration)

            if not in_bunker:
                # Hill bounce logic: add a kick based on the slope
                slope_x, slope_y = get_slope_at_point(self.x, self.y, fairway_nodes, green_z)
                kick_magnitude = math.hypot(dampened_vx, dampened_vy) * 1.2 # Strong kick downhill
                
                self.vx = dampened_vx - slope_x * kick_magnitude
                self.vy = dampened_vy - slope_y * kick_magnitude
            else:
                # Bunkers absorb the impact, no slope kick
                self.vx = dampened_vx
                self.vy = dampened_vy
            
            self.angle = math.degrees(math.atan2(self.vx, self.vy))
            self.max_height = self.height
            self.wind_x *= 0.5
            self.wind_y *= 0.5
            self.curve_accel_x *= 0.3
            self.curve_accel_y *= 0.3
            
            self.start_z = get_elevation(self.x, self.y, fairway_nodes, green_z)
            target_x_est = self.x + self.vx * self.flight_duration
            target_y_est = self.y + self.vy * self.flight_duration
            target_elev = get_elevation(target_x_est, target_y_est, fairway_nodes, green_z)
            self.elev_diff = target_elev - self.start_z

    def update(self, fairway_nodes, green_z, bunkers):
        if self.is_moving:
            self.flight_progress += 1
            t = self.flight_progress / self.flight_duration
            absolute_z = self.start_z + 4 * self.max_height * t * (1 - t) + (self.elev_diff * t)
            current_ground_z = get_elevation(self.x, self.y, fairway_nodes, green_z)
            self.z = absolute_z - current_ground_z
            
            self.vx += self.curve_accel_x
            self.vy += self.curve_accel_y
            
            # Wind affects the ball more at higher altitudes
            altitude_wind_mult = max(0, self.z) / 40.0
            self.x += self.vx + (self.wind_x * altitude_wind_mult)
            self.y += self.vy + (self.wind_y * altitude_wind_mult)
            
            if self.z <= 0 or self.flight_progress >= self.flight_duration:
                self.z = 0
                self.start_bounce(fairway_nodes, green_z, bunkers)

def project(obj_x, obj_y, obj_z, cam_x, cam_y, cam_angle, w, h):
    global cam_z_global
    rel_x = obj_x - cam_x
    rel_y = obj_y - cam_y
    
    # Rotate around the camera so the view aligns with our aim
    rad = math.radians(cam_angle)
    rx = rel_x * math.cos(rad) - rel_y * math.sin(rad)
    ry = rel_x * math.sin(rad) + rel_y * math.cos(rad)
    
    orig_ry = ry
    NEAR_PLANE = -14.0
    if ry < NEAR_PLANE:
        # Correctly clip the point to the near plane to prevent wide stretching
        scale = NEAR_PLANE / ry
        rx = rx * scale
        ry = NEAR_PLANE
            
    factor = (h * 0.5) / (ry + 15)
    sx = (w // 2) + (rx * factor)
    horizon = h * 0.38
    rel_z = obj_z - cam_z_global
    sy = horizon + (h - horizon) * (15 / (ry + 15)) - (rel_z * factor)
    return int(sx), int(sy), factor, orig_ry

def draw_hud(screen, curr_w, curr_h, ball, hole_pos, club_idx, power, wx, wy, is_swinging, trajectory_offset, face_angle, cam_angle, hole_idx, par, show_adv_stats, active_peers, player_id):
    # --- Club Inventory (Left Side) ---
    pygame.draw.rect(screen, (0,0,0,100), (10, 34, 180, 330))
    for i, c in enumerate(CLUBS):
        color = YELLOW if i == club_idx else WHITE
        txt = font_small.render(f"{c[0]}: {c[1]}y", True, color)
        screen.blit(txt, (20, 44 + i * 22))

    # --- Wind & Distance (Right Side) ---
    screen.blit(font_med.render(f"HOLE {hole_idx+1} - PAR {par}", True, WHITE), (curr_w - 280, 34))
    dist = int(math.hypot(ball.x-hole_pos[0], ball.y-hole_pos[1]))
    screen.blit(font_med.render(f"{dist} YDS TO PIN", True, WHITE), (curr_w - 280, 74))
    screen.blit(font_med.render(f"STROKES: {ball.strokes}", True, WHITE), (curr_w - 280, 114))
    
    screen.blit(font_small.render(f"PLAYER ID: {player_id}", True, YELLOW), (curr_w - 280, 150))
    screen.blit(font_small.render(f"PEERS ONLINE: {len(active_peers)}", True, (255, 150, 150)), (curr_w - 280, 170))
    
    # Trackman Data Panel
    panel_y = 200
    screen.blit(font_small.render(f"LIE: {ball.lie}%", True, WHITE if ball.lie >= 90 else YELLOW), (curr_w - 280, panel_y))
    
    loft_str = f"+{int(trajectory_offset)}" if trajectory_offset > 0 else str(int(trajectory_offset))
    screen.blit(font_small.render(f"LOFT OFFSET: {loft_str}°", True, WHITE), (curr_w - 280, panel_y + 25))
    
    if ball.is_moving:
        d_loft, l_angle, s_loft, display_rpm = ball.dynamic_loft, ball.launch_angle, ball.spin_loft, ball.rpm
    else:
        d_loft, l_angle, s_loft, display_rpm = calculate_trackman_stats(club_idx, trajectory_offset, 1.0)
        
    if show_adv_stats:
        screen.blit(font_small.render(f"DYN LOFT: {d_loft:.1f}°", True, WHITE), (curr_w - 280, panel_y + 50))
        screen.blit(font_small.render(f"SPIN LOFT: {s_loft:.1f}°", True, WHITE), (curr_w - 280, panel_y + 75))
        screen.blit(font_small.render(f"LAUNCH ANG: {l_angle:.1f}°", True, WHITE), (curr_w - 280, panel_y + 100))
        screen.blit(font_small.render(f"SPIN RATE: {display_rpm} RPM", True, WHITE), (curr_w - 280, panel_y + 125))
        face_str = f"{abs(face_angle):.1f}° {'OPEN' if face_angle > 0 else 'CLOSED' if face_angle < 0 else 'SQUARE'}"
        screen.blit(font_small.render(f"FACE: {face_str}", True, WHITE), (curr_w - 280, panel_y + 150))
        compass_y = panel_y + 215
    else:
        screen.blit(font_small.render(f"SPIN: {display_rpm} RPM", True, WHITE), (curr_w - 280, panel_y + 50))
        face_str = f"{abs(face_angle):.1f}° {'OPEN' if face_angle > 0 else 'CLOSED' if face_angle < 0 else 'SQUARE'}"
        screen.blit(font_small.render(f"FACE: {face_str}", True, WHITE), (curr_w - 280, panel_y + 75))
        compass_y = panel_y + 140
    
    # Wind Compass
    cx, cy = curr_w - 80, compass_y
    pygame.draw.circle(screen, WHITE, (cx, cy), 40, 2)
    mag = math.hypot(wx, wy)
    if mag > 0:
        rad = math.radians(cam_angle)
        local_wx = wx * math.cos(rad) - wy * math.sin(rad)
        local_wy = wx * math.sin(rad) + wy * math.cos(rad)
        ex, ey = cx + (local_wx/mag)*35, cy - (local_wy/mag)*35
        pygame.draw.line(screen, YELLOW, (cx, cy), (ex, ey), 3)
    screen.blit(font_small.render(f"WIND: {int(mag)} MPH", True, WHITE), (cx - 55, cy + 50))

    # --- Power Meter (Bottom Center) ---
    if is_swinging or power > 0:
        mw, mh = 300, 25
        mx, my = curr_w // 2 - mw // 2, curr_h - 100
        pygame.draw.rect(screen, GRAY, (mx, my, mw, mh))
        pygame.draw.rect(screen, YELLOW, (mx, my, int(mw * power), mh))
        pygame.draw.rect(screen, WHITE, (mx, my, mw, mh), 2)
        label = font_small.render(f"POWER: {int(power*100)}%", True, WHITE)
        screen.blit(label, (mx + 100, my - 25))

def draw_menus(screen, curr_w, active_menu, show_wind_preview, show_adv_stats):
    pygame.draw.rect(screen, (200, 200, 200), (0, 0, curr_w, 24))
    pygame.draw.line(screen, (100, 100, 100), (0, 24), (curr_w, 24))

    f_bg = (150, 150, 150) if active_menu == "File" else (200, 200, 200)
    pygame.draw.rect(screen, f_bg, (0, 0, 60, 24))
    screen.blit(font_small.render("File", True, (0, 0, 0)), (12, 1))

    o_bg = (150, 150, 150) if active_menu == "Options" else (200, 200, 200)
    pygame.draw.rect(screen, o_bg, (60, 0, 100, 24))
    screen.blit(font_small.render("Options", True, (0, 0, 0)), (70, 1))

    h_bg = (150, 150, 150) if active_menu == "Hole" else (200, 200, 200)
    pygame.draw.rect(screen, h_bg, (160, 0, 80, 24))
    screen.blit(font_small.render("Hole", True, (0, 0, 0)), (175, 1))

    if active_menu == "File":
        pygame.draw.rect(screen, (220, 220, 220), (0, 24, 120, 60))
        pygame.draw.rect(screen, (100, 100, 100), (0, 24, 120, 60), 1)
        screen.blit(font_small.render("Restart", True, (0, 0, 0)), (10, 28))
        screen.blit(font_small.render("Quit", True, (0, 0, 0)), (10, 54))
    elif active_menu == "Options":
        pygame.draw.rect(screen, (220, 220, 220), (60, 24, 200, 86))
        pygame.draw.rect(screen, (100, 100, 100), (60, 24, 200, 86), 1)
        chk = "[X]" if show_wind_preview else "[ ]"
        screen.blit(font_small.render(f"{chk} Wind Preview", True, (0, 0, 0)), (70, 28))
        chk_adv = "[X]" if show_adv_stats else "[ ]"
        screen.blit(font_small.render(f"{chk_adv} Advanced Stats", True, (0, 0, 0)), (70, 54))
        screen.blit(font_small.render("    View Scorecard (C)", True, (0, 0, 0)), (70, 80))
    elif active_menu == "Hole":
        pygame.draw.rect(screen, (220, 220, 220), (160, 24, 160, 86))
        pygame.draw.rect(screen, (100, 100, 100), (160, 24, 160, 86), 1)
        screen.blit(font_small.render("Next Hole (N)", True, (0, 0, 0)), (170, 28))
        screen.blit(font_small.render("Prev Hole (P)", True, (0, 0, 0)), (170, 54))
        screen.blit(font_small.render("Unplayable (U)", True, (0, 0, 0)), (170, 80))

def draw_scorecard(screen, curr_w, curr_h, group_scores, course, current_tee_order):
    overlay = pygame.Surface((curr_w, curr_h), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 180))
    screen.blit(overlay, (0, 0))

    sw = 820
    num_players = len(current_tee_order)
    sh = 240 + (num_players * 30 * 2) 
    sx, sy = curr_w//2 - sw//2, curr_h//2 - sh//2
    pygame.draw.rect(screen, (240, 240, 240), (sx, sy, sw, sh), border_radius=10)
    pygame.draw.rect(screen, HOLE_COLOR, (sx, sy, sw, sh), 4, border_radius=10)

    title = font_large.render("SCORECARD", True, HOLE_COLOR)
    screen.blit(title, (curr_w//2 - title.get_width()//2, sy + 15))

    def draw_grid(x, y, start_hole, end_hole, label_total1, label_total2=None):
        col_w = 55
        name_w = 160
        cols = 12 if label_total2 else 11
        total_width = name_w + col_w * (cols - 1)
        
        pygame.draw.rect(screen, (200, 200, 200), (x, y, total_width, 30))
        
        def get_cx(i):
            return x + name_w//2 if i == 0 else x + name_w + (i-1)*col_w + col_w//2
        
        headers = ["HOLE"] + [str(i+1) for i in range(start_hole, end_hole)] + [label_total1]
        if label_total2: headers.append(label_total2)
        for i, h_txt in enumerate(headers):
            surf = font_small.render(h_txt, True, HOLE_COLOR)
            screen.blit(surf, (get_cx(i) - surf.get_width()//2, y + 6))
            
        y += 30
        out_par = sum(c["par"] for c in course[start_hole:end_hole])
        pars = ["PAR"] + [str(course[i]["par"]) for i in range(start_hole, end_hole)] + [str(out_par)]
        if label_total2: pars.append(str(sum(c["par"] for c in course)))
        for i, p_txt in enumerate(pars):
            surf = font_small.render(p_txt, True, HOLE_COLOR)
            screen.blit(surf, (get_cx(i) - surf.get_width()//2, y + 6))
            
        y += 30
        
        for p_idx, p_id in enumerate(current_tee_order):
            p_scores = group_scores.get(p_id, [None]*18)
            out_score = sum(p_scores[i] for i in range(start_hole, end_hole) if p_scores[i] is not None)
            out_score_txt = str(out_score) if any(p_scores[i] is not None for i in range(start_hole, end_hole)) else "-"
            
            display_name = p_id[:10]
            s_row = [display_name] + [str(p_scores[i]) if p_scores[i] is not None else "-" for i in range(start_hole, end_hole)] + [out_score_txt]
            if label_total2:
                tot = sum(s for s in p_scores if s is not None)
                s_row.append(str(tot) if any(s is not None for s in p_scores) else "-")

            for i, s_txt in enumerate(s_row):
                color = HOLE_COLOR
                is_score = i > 0 and i <= (end_hole - start_hole) and s_txt != "-"
                if is_score:
                    diff = int(s_txt) - course[start_hole + i - 1]["par"]
                    if diff < 0: color = RED
                    elif diff > 0: color = (0, 0, 200)
                    
                surf = font_small.render(s_txt, True, color)
                cx = get_cx(i)
                cy = y + 6 + surf.get_height()//2
                
                if is_score:
                    if diff == -1: # Birdie
                        pygame.draw.circle(screen, color, (cx, cy), 13, 2)
                    elif diff <= -2: # Eagle or better
                        pygame.draw.circle(screen, color, (cx, cy), 11, 2)
                        pygame.draw.circle(screen, color, (cx, cy), 16, 2)
                    elif diff == 1: # Bogey
                        pygame.draw.rect(screen, color, (cx - 12, cy - 12, 24, 24), 2)
                    elif diff >= 2: # Double Bogey or worse
                        pygame.draw.rect(screen, color, (cx - 11, cy - 11, 22, 22), 2)
                        pygame.draw.rect(screen, color, (cx - 16, cy - 16, 32, 32), 2)

                screen.blit(surf, (cx - surf.get_width()//2, y + 6))
            y += 30
            
        total_rows = 2 + num_players
        start_y = y - (total_rows * 30)
        for r in range(total_rows + 1): pygame.draw.line(screen, GRAY, (x, start_y + r*30), (x + total_width, start_y + r*30))
        pygame.draw.line(screen, GRAY, (x, start_y), (x, start_y + total_rows*30))
        for c in range(cols): pygame.draw.line(screen, GRAY, (x + name_w + c*col_w, start_y), (x + name_w + c*col_w, start_y + total_rows*30))

    grid1_y = sy + 70
    grid2_y = grid1_y + 30 * (2 + num_players) + 20
    draw_grid(curr_w//2 - (160 + 55*10)//2, grid1_y, 0, 9, "OUT")
    draw_grid(curr_w//2 - (160 + 55*11)//2, grid2_y, 9, 18, "IN", "TOT")
    
    close_y = grid2_y + 30 * (2 + num_players) + 20
    close_txt = font_small.render("Press 'C' to Close Scorecard", True, GRAY)
    screen.blit(close_txt, (curr_w//2 - close_txt.get_width()//2, close_y))

def main():
    difficulty = None
    player_name = ""
    input_active = False
    
    course_list = [
        ("Meigs Field Golf Course (Easy)", 312),
        ("Central Park", 212),
        ("Augusta Pines", 123),
        ("Mirage Dunes", 789),
        ("Augusta National", 1934)
    ]
    course_idx = 0
    
    options = [
        {"text": "1. Beginner (No Wind)", "diff": 0, "rect": pygame.Rect(0, 0, 0, 0)},
        {"text": "2. Amateur (Light Wind)", "diff": 15, "rect": pygame.Rect(0, 0, 0, 0)},
        {"text": "3. Pro (Heavy Wind)", "diff": 30, "rect": pygame.Rect(0, 0, 0, 0)}
    ]

    while difficulty is None:
        curr_w, curr_h = screen.get_size()
        screen.fill((30, 30, 30))
        
        mouse_pos = pygame.mouse.get_pos()
        
        # --- Course Selection Carousel ---
        current_course_name = course_list[course_idx][0]
        title = font_large.render(current_course_name.upper(), True, WHITE)
        title_x = curr_w//2 - title.get_width()//2
        title_y = 100
        screen.blit(title, (title_x, title_y))
        
        left_rect = pygame.Rect(title_x - 60, title_y, 40, 50)
        right_rect = pygame.Rect(title_x + title.get_width() + 20, title_y, 40, 50)
        
        left_color = YELLOW if left_rect.collidepoint(mouse_pos) else WHITE
        right_color = YELLOW if right_rect.collidepoint(mouse_pos) else WHITE
        
        screen.blit(font_large.render("<", True, left_color), (left_rect.x, left_rect.y))
        screen.blit(font_large.render(">", True, right_color), (right_rect.x, right_rect.y))
        
        course_lbl = font_small.render("SELECT COURSE", True, (150, 150, 150))
        screen.blit(course_lbl, (curr_w//2 - course_lbl.get_width()//2, title_y - 25))
        
        name_rect = pygame.Rect(curr_w//2 - 200, 190, 400, 50)
        is_hover_name = name_rect.collidepoint(mouse_pos)
        pygame.draw.rect(screen, FAIRWAY if is_hover_name or input_active else ROUGH, name_rect, border_radius=8)
        pygame.draw.rect(screen, YELLOW if input_active else WHITE, name_rect, 2, border_radius=8)
        cursor = "_" if input_active and time.time() % 1 < 0.5 else ""
        name_surf = font_med.render(f"Name: {player_name}{cursor}", True, WHITE)
        screen.blit(name_surf, (name_rect.x + 15, name_rect.centery - name_surf.get_height()//2))
        
        for i, opt in enumerate(options):
            rect = pygame.Rect(curr_w//2 - 200, 260 + i * 70, 400, 50)
            opt["rect"] = rect
            is_hover = rect.collidepoint(mouse_pos)
            
            pygame.draw.rect(screen, FAIRWAY if is_hover else ROUGH, rect, border_radius=8)
            pygame.draw.rect(screen, WHITE, rect, 2, border_radius=8)
            
            text_surf = font_med.render(opt["text"], True, WHITE if is_hover else YELLOW)
            screen.blit(text_surf, (rect.centerx - text_surf.get_width()//2, rect.centery - text_surf.get_height()//2))
            
        pygame.display.flip()
        for e in pygame.event.get():
            if e.type == pygame.QUIT: pygame.quit(); return
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_1: difficulty = 0
                if e.key == pygame.K_2: difficulty = 8
                if e.key == pygame.K_3: difficulty = 18
                if input_active:
                    if e.key == pygame.K_RETURN:
                        input_active = False
                    elif e.key == pygame.K_BACKSPACE:
                        player_name = player_name[:-1]
                    elif len(player_name) < 10 and e.unicode.isprintable():
                        player_name += e.unicode
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if left_rect.collidepoint(e.pos):
                    course_idx = (course_idx - 1) % len(course_list)
                    input_active = False
                elif right_rect.collidepoint(e.pos):
                    course_idx = (course_idx + 1) % len(course_list)
                    input_active = False
                elif name_rect.collidepoint(e.pos):
                    input_active = True
                else:
                    input_active = False
                    for opt in options:
                        if opt["rect"].collidepoint(e.pos):
                            difficulty = opt["diff"]
                            
    selected_course = Course(course_list[course_idx][0], course_list[course_idx][1])
                        
    network = P2PNetwork(player_id=player_name)

    hole_idx = 0
    scores = [None] * 18
    hole_data = selected_course.holes[hole_idx]
    green_center = hole_data["hole_pos"]
    pin_positions = hole_data.get("pin_positions", [green_center])
    
    wind_rng = random.Random(312 + hole_idx)
    wx, wy = wind_rng.uniform(-difficulty, difficulty), wind_rng.uniform(-difficulty, difficulty)
    pin_idx = wind_rng.randint(0, len(pin_positions) - 1)
    hole_pos = pin_positions[pin_idx]
    
    fairway_nodes = hole_data["fairway"]
    par = hole_data["par"]
    green_shape = hole_data["green"]
    slope_waves = hole_data["slope_waves"]
    green_z = hole_data["green_z"]
    bunkers = hole_data["bunkers"]
    water_hazards = hole_data.get("water", [])
    trees = hole_data["trees"]

    ball = Ball()
    cam_x, cam_y = 0, -20
    aim_angle = math.degrees(math.atan2(hole_pos[0], hole_pos[1]))
    cam_angle = aim_angle
    trajectory_offset = 0.0
    face_angle = 0.0
    show_wind_preview = False
    show_scorecard = False
    show_adv_stats = True
    club_idx = 0
    state = "3D"
    
    is_swinging = False
    power = 0.0
    msg_text = ""
    msg_timer = 0
    active_menu = None
    particles = []
    jump_hole_dir = 0
    take_unplayable = False
    
    current_tee_order = [network.player_id]
    peer_hole_scores = {}

    running = True
    while running:
        curr_w, curr_h = screen.get_size()
        mouse_pos = pygame.mouse.get_pos()
        screen.fill(SKY)
        
        # Update network state
        my_state = {
            'hole': hole_idx,
            'state': state,
            'strokes': ball.strokes,
            'x': ball.x,
            'y': ball.y,
            'z': ball.z,
            'putt_x': ball.putt_x,
            'putt_y': ball.putt_y,
            'putt_z': ball.putt_z,
            'scores': scores
        }
        network.broadcast_state(my_state)
        active_peers = network.get_active_peers()

        # Grouping and Tee Order Tracking
        for p_id, p_state in active_peers:
            if p_state['hole'] == hole_idx and p_id not in current_tee_order:
                current_tee_order.append(p_id)
            if p_state['state'] == "HOLE":
                if p_id not in peer_hole_scores:
                    peer_hole_scores[p_id] = {}
                peer_hole_scores[p_id][p_state['hole']] = p_state['strokes']

        my_turn = True
        waiting_on = None
        if ball.strokes == 0 and state == "3D" and not ball.is_moving:
            my_idx = current_tee_order.index(network.player_id)
            for before_id in current_tee_order[:my_idx]:
                peer_state = next((p for p_id, p in active_peers if p_id == before_id), None)
                if peer_state and peer_state['hole'] == hole_idx and peer_state['strokes'] == 0:
                    my_turn = False
                    waiting_on = before_id
                    break
                    
        waiting_for_others = False
        if state == "HOLE":
            group_active_peers = {p_id: p for p_id, p in active_peers if p_id in current_tee_order}
            for p_id, p in group_active_peers.items():
                if p['hole'] == hole_idx and p['state'] != "HOLE":
                    waiting_for_others = True

        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
            
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                handled_menu = False
                if active_menu == "File" and pygame.Rect(0, 24, 120, 60).collidepoint(event.pos):
                    if event.pos[1] < 54:
                        main(); return
                    else:
                        running = False
                    handled_menu = True
                elif active_menu == "Options" and pygame.Rect(60, 24, 200, 86).collidepoint(event.pos):
                    if event.pos[1] < 50: show_wind_preview = not show_wind_preview
                    elif event.pos[1] < 76: show_adv_stats = not show_adv_stats
                    else: show_scorecard = not show_scorecard
                    handled_menu = True
                elif active_menu == "Hole" and pygame.Rect(160, 24, 160, 86).collidepoint(event.pos):
                    if event.pos[1] < 50: jump_hole_dir = 1
                    elif event.pos[1] < 76: jump_hole_dir = -1
                    else: take_unplayable = True
                    handled_menu = True
                
                if not handled_menu:
                    if pygame.Rect(0, 0, 60, 24).collidepoint(event.pos): active_menu = "File"; handled_menu = True
                    elif pygame.Rect(60, 0, 100, 24).collidepoint(event.pos): active_menu = "Options"; handled_menu = True
                    elif pygame.Rect(160, 0, 80, 24).collidepoint(event.pos): active_menu = "Hole"; handled_menu = True
                    else: active_menu = None
                else:
                    active_menu = None
                    
                if handled_menu: continue

            if event.type == pygame.KEYDOWN:
                # Disabled ESC / Q quit to prevent accidental closing
                # if event.key == pygame.K_ESCAPE: running = False
                if event.key == pygame.K_q: pass 
                if event.key == pygame.K_c: show_scorecard = not show_scorecard
                if event.key == pygame.K_n: jump_hole_dir = 1
                if event.key == pygame.K_p: jump_hole_dir = -1
                if event.key == pygame.K_u: take_unplayable = True
                
                if (not ball.is_moving and not is_swinging and state == "3D") or \
                   (state == "GREEN" and ball.putt_vx == 0 and ball.putt_vy == 0 and ball.putt_z == 0 and not ball.is_dragging and ball.chipping):
                    if event.key == pygame.K_a: face_angle -= 1.0
                    if event.key == pygame.K_d: face_angle += 1.0
                
                if state == "GREEN" and ball.putt_vx == 0 and ball.putt_vy == 0 and ball.putt_z == 0:
                    if event.key == pygame.K_SPACE:
                        ball.chipping = not ball.chipping
                    if event.key == pygame.K_w: club_idx = (club_idx - 1) % len(CLUBS)
                    if event.key == pygame.K_s: club_idx = (club_idx + 1) % len(CLUBS)

                if not ball.is_moving and state == "3D":
                    if event.key == pygame.K_w: club_idx = (club_idx - 1) % len(CLUBS)
                    if event.key == pygame.K_s: club_idx = (club_idx + 1) % len(CLUBS)
                    if event.key == pygame.K_SPACE:
                        if my_turn:
                            is_swinging = True; power = 0.0
                        else:
                            msg_text = f"WAIT FOR {waiting_on} TO TEE OFF!"
                            msg_timer = 60

            if event.type == pygame.KEYUP:
                if event.key == pygame.K_SPACE and is_swinging:
                    effective_power = power * (ball.lie / 100.0)
                    dist = CLUBS[club_idx][1] - (trajectory_offset * 2.5)
                    height = CLUBS[club_idx][2] + (trajectory_offset * 1.5)
                    
                    in_bunker = any(math.hypot(ball.x - bx, ball.y - by) < br for bx, by, br, _ in bunkers)
                    if in_bunker:
                        for _ in range(40):
                            particles.append({
                                'x': ball.x + random.uniform(-0.2, 0.2), 'y': ball.y + random.uniform(-0.2, 0.2), 'z': 0,
                                'vx': random.uniform(-0.8, 0.8), 'vy': random.uniform(-0.8, 0.8), 'vz': random.uniform(1.0, 3.0),
                                'life': random.randint(20, 40),
                                'color': random.choice([(210, 180, 140), (190, 160, 120), (220, 190, 150)])
                            })
                            
                    ball.start_flight(dist, height, aim_angle, wx, wy, effective_power, trajectory_offset, club_idx, face_angle, fairway_nodes, green_z)
                    is_swinging = False; power = 0.0

            # Putting Event Handling
            if state == "GREEN" and ball.putt_vx == 0 and ball.putt_vy == 0 and ball.putt_z == 0:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    ball.is_dragging = True
                if event.type == pygame.MOUSEBUTTONUP and ball.is_dragging:
                    ball.prev_x = hole_pos[0] + (ball.putt_x - curr_w//2) / PPU
                    ball.prev_y = hole_pos[1] - (ball.putt_y - curr_h//2) / PPU
                    power_mult = ball.lie / 100.0
                    
                    sim_x = ball.prev_x
                    sim_y = ball.prev_y
                    in_bunker = any(math.hypot(sim_x - bx, sim_y - by) < br for bx, by, br, _ in bunkers)
                    if in_bunker and ball.chipping:
                        for _ in range(30):
                            particles.append({
                                'x': sim_x + random.uniform(-0.2, 0.2), 'y': sim_y + random.uniform(-0.2, 0.2), 'z': 0,
                                'vx': random.uniform(-0.5, 0.5), 'vy': random.uniform(-0.5, 0.5), 'vz': random.uniform(0.5, 2.0),
                                'life': random.randint(15, 30),
                                'color': random.choice([(210, 180, 140), (190, 160, 120), (220, 190, 150)])
                            })
                            
                    drag_dx = (ball.putt_x - mouse_pos[0]) / PPU
                    drag_dy = (ball.putt_y - mouse_pos[1]) / PPU
                    
                    mods = pygame.key.get_mods()
                    power_boost = 3.0 if mods & pygame.KMOD_SHIFT else 1.0
                    
                    if ball.chipping:
                        club_pwr = CLUBS[club_idx][1] / 125.0
                        club_lft = CLUBS[club_idx][3] / 46.0
                        ball.putt_vx = drag_dx * 4.2 * power_mult * club_pwr * power_boost
                        ball.putt_vy = drag_dy * 4.2 * power_mult * club_pwr * power_boost
                        drag_dist = math.hypot(drag_dx, drag_dy)
                        ball.putt_vz = drag_dist * 4.2 * club_lft * power_boost
                    else:
                        ball.putt_vx = drag_dx * 3.5 * power_mult * power_boost
                        ball.putt_vy = drag_dy * 3.5 * power_mult * power_boost
                        ball.putt_vz = 0
                    ball.strokes += 1
                    ball.is_dragging = False

            if state == "HOLE":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    if waiting_for_others:
                        msg_text = "WAITING FOR GROUP TO FINISH"
                        msg_timer = 60
                    else:
                        show_scorecard = False
                        
                        # Calculate Next Tee Order
                        scores_for_sort = {network.player_id: ball.strokes}
                        for p_id in current_tee_order:
                            if p_id == network.player_id: continue
                            scores_for_sort[p_id] = peer_hole_scores.get(p_id, {}).get(hole_idx, 999)
                            
                        def sort_key(p_id):
                            score = scores_for_sort.get(p_id, 999)
                            tiebreaker = current_tee_order.index(p_id) if p_id in current_tee_order else 999
                            return (score, tiebreaker)
                            
                        current_tee_order = sorted(current_tee_order, key=sort_key)
                        
                        hole_idx += 1
                        if hole_idx >= len(selected_course.holes):
                            main() # Restart game if 18 holes are finished
                            return
                        hole_data = selected_course.holes[hole_idx]
                        green_center = hole_data["hole_pos"]
                        pin_positions = hole_data.get("pin_positions", [green_center])
                        
                        wind_rng = random.Random(312 + hole_idx)
                        wx, wy = wind_rng.uniform(-difficulty, difficulty), wind_rng.uniform(-difficulty, difficulty)
                        pin_idx = wind_rng.randint(0, len(pin_positions) - 1)
                        hole_pos = pin_positions[pin_idx]
                        
                        fairway_nodes = hole_data["fairway"]
                        par = hole_data["par"]
                        green_shape = hole_data["green"]
                        slope_waves = hole_data["slope_waves"]
                        green_z = hole_data["green_z"]
                        bunkers = hole_data["bunkers"]
                        water_hazards = hole_data.get("water", [])
                        trees = hole_data["trees"]
                        ball = Ball()
                        cam_x, cam_y = 0, -20
                        aim_angle = math.degrees(math.atan2(hole_pos[0], hole_pos[1]))
                        cam_angle = aim_angle
                        trajectory_offset = 0.0
                        face_angle = 0.0
                        state = "3D"
                        is_swinging = False; power = 0.0

        if is_swinging:
            power += 0.015
            if power > 1.0: power = 0.0 # Reset on over-swing

        keys = pygame.key.get_pressed()
        is_stat_3d = not ball.is_moving and not is_swinging and state == "3D"
        is_stat_2d = state == "GREEN" and ball.putt_vx == 0 and ball.putt_vy == 0 and ball.putt_z == 0 and not ball.is_dragging
        
        if is_stat_3d or (is_stat_2d and ball.chipping):
            if keys[pygame.K_UP]: trajectory_offset += 0.5
            if keys[pygame.K_DOWN]: trajectory_offset -= 0.5
            
            club_name = CLUBS[club_idx][0]
            if club_name == "LW": min_offset = -30.0
            elif club_name == "SW": min_offset = -28.0
            elif club_name == "GW": min_offset = -24.0
            elif club_name == "PW": min_offset = -21.5
            else: min_offset = -15.0
            
            trajectory_offset = max(min_offset, min(15.0, trajectory_offset))
            face_angle = max(-15.0, min(15.0, face_angle))
            
        if is_stat_3d:
            if keys[pygame.K_LEFT]: aim_angle -= 0.8
            if keys[pygame.K_RIGHT]: aim_angle += 0.8

        # --- Game Logic ---
        for p in particles[:]:
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['z'] += p['vz']
            p['vz'] -= 0.15 # Gravity
            p['life'] -= 1
            if p['life'] <= 0 or p['z'] < 0:
                particles.remove(p)
                
        if state == "3D":
            was_moving = ball.is_moving
            ball.update(fairway_nodes, green_z, bunkers)
            
            if ball.is_moving and not ball.hit_tree:
                for tree_data in trees:
                    tx, ty, tz, th, tw = tree_data[:5]
                    if math.hypot(ball.x - tx, ball.y - ty) < tw * 0.8:
                        if ball.z <= tz + th:
                            ball.hit_tree = True
                            ball.vx *= -0.2
                            ball.vy *= -0.2
                            ball.wind_x = 0
                            ball.wind_y = 0
                            ball.curve_accel_x = 0
                            ball.curve_accel_y = 0
                            if ball.flight_progress < ball.flight_duration / 2:
                                ball.flight_progress = ball.flight_duration - ball.flight_progress
                            msg_text = "TREE HIT!"
                            msg_timer = 90
                            break
            
            if ball.is_moving and ball.z <= 0.5:
                in_water = any(math.hypot(ball.x - haz_x, ball.y - haz_y) < haz_r for haz_x, haz_y, haz_r in water_hazards)
                if in_water:
                    for _ in range(40):
                        particles.append({
                            'x': ball.x + random.uniform(-0.5, 0.5), 'y': ball.y + random.uniform(-0.5, 0.5), 'z': 0,
                            'vx': random.uniform(-0.5, 0.5), 'vy': random.uniform(-0.5, 0.5), 'vz': random.uniform(1.0, 4.0),
                            'life': random.randint(20, 40),
                            'color': (200, 220, 255)
                        })
                    ball.is_moving = False
                    ball.strokes += 1
                    ball.x, ball.y = ball.prev_x, ball.prev_y
                    ball.z = 0
                    ball.vx = ball.vy = 0
                    msg_text = "WATER HAZARD! +1 STROKE"
                    msg_timer = 180
            
            cam_angle += (aim_angle - cam_angle) * 0.1
            target_cam_x = ball.x - math.sin(math.radians(cam_angle)) * 18
            target_cam_y = ball.y - math.cos(math.radians(cam_angle)) * 18
            cam_x += (target_cam_x - cam_x) * 0.1
            cam_y += (target_cam_y - cam_y) * 0.1
            
            global cam_z_global
            cam_z_global = get_elevation(cam_x, cam_y, fairway_nodes, green_z) + 4.5
            
            if was_moving and not ball.is_moving:
                # Find nearest fairway node to determine boundaries dynamically
                closest_x = 0
                closest_w = 30
                min_dist = 9999
                for y, x, w, *_ in fairway_nodes:
                    if abs(y - ball.y) < min_dist:
                        min_dist = abs(y - ball.y)
                        closest_x = x
                        closest_w = w
                        
                if abs(ball.x - closest_x) > 120 or ball.y < -50 or ball.y > hole_pos[1] + 50:
                    ball.strokes += 2
                    ball.x, ball.y = ball.prev_x, ball.prev_y
                    msg_text = "OUT OF BOUNDS! +2 STROKES"
                    msg_timer = 180
                elif is_in_chipping_range(ball.x, ball.y, green_center, green_shape, buffer_yards=10):
                    proj_x = curr_w // 2 + (ball.x - hole_pos[0]) * PPU
                    proj_y = curr_h // 2 + (hole_pos[1] - ball.y) * PPU
                    on_green = is_on_green(ball.x, ball.y, green_center, green_shape)
                    margin = 250
                    if on_green or (margin < proj_x < curr_w - margin and margin < proj_y < curr_h - margin):
                        state = "GREEN"
                        ball.putt_x = proj_x
                        ball.putt_y = proj_y
                        if on_green:
                            ball.lie = 100
                            ball.chipping = False
                        else:
                            in_bunker = any(math.hypot(ball.x - bx, ball.y - by) < br for bx, by, br, _ in bunkers)
                            if in_bunker:
                                ball.lie = random.randint(15, 85)
                                ball.chipping = True
                            else:
                                ball.lie = random.randint(30, 90)
                                ball.chipping = True if ball.lie < 70 else False
                    else:
                        in_bunker = any(math.hypot(ball.x - bx, ball.y - by) < br for bx, by, br, _ in bunkers)
                        if in_bunker:
                            ball.lie = random.randint(15, 85)
                        elif abs(ball.x - closest_x) <= closest_w:
                            ball.lie = 100
                        else:
                            ball.lie = random.randint(30, 100)
                else:
                    in_bunker = any(math.hypot(ball.x - bx, ball.y - by) < br for bx, by, br, _ in bunkers)
                    if in_bunker:
                        ball.lie = random.randint(15, 85)
                    elif abs(ball.x - closest_x) <= closest_w:
                        ball.lie = 100
                    else:
                        ball.lie = random.randint(30, 100)

        elif state == "GREEN":
            was_moving_2d = ball.putt_vx != 0 or ball.putt_vy != 0 or ball.putt_z > 0
            
            if ball.putt_z > 0 or ball.putt_vz != 0:
                ball.putt_x += ball.putt_vx
                ball.putt_y += ball.putt_vy
                ball.putt_z += ball.putt_vz
                ball.putt_vz -= 2.3 # Gravity
                
                if ball.putt_z <= 0:
                    ball.putt_z = 0
                    ball.putt_vz = 0
                    
                    sim_x = hole_pos[0] + (ball.putt_x - curr_w//2) / PPU
                    sim_y = hole_pos[1] - (ball.putt_y - curr_h//2) / PPU
                    if any(math.hypot(sim_x - bx, sim_y - by) < br for bx, by, br, _ in bunkers):
                        ball.putt_vx *= 0.1
                        ball.putt_vy *= 0.1
                    else:
                        roll_factor = max(0.1, 0.4 + (1.0 - (CLUBS[club_idx][3] / 46.0)) * 0.6) if ball.chipping else 0.4
                        ball.putt_vx *= roll_factor
                        ball.putt_vy *= roll_factor
            else:
                ball.putt_x += ball.putt_vx; ball.putt_y += ball.putt_vy
                
                sim_x = hole_pos[0] + (ball.putt_x - curr_w//2) / PPU
                sim_y = hole_pos[1] - (ball.putt_y - curr_h//2) / PPU
                
                if is_on_green(sim_x, sim_y, green_center, green_shape):
                    sx, sy = get_slope(sim_x, sim_y, slope_waves, pin_positions)
                    ball.putt_vx += sx * 2.8
                    ball.putt_vy += sy * 2.8
                    ball.putt_vx *= 0.97
                    ball.putt_vy *= 0.97
                    if math.hypot(ball.putt_vx, ball.putt_vy) < 0.7 and math.hypot(sx, sy) < 0.02:
                        ball.putt_vx *= 0.5  # Strong static friction to prevent endless rolling
                        ball.putt_vy *= 0.5
                else:
                    in_water = any(math.hypot(sim_x - haz_x, sim_y - haz_y) < haz_r for haz_x, haz_y, haz_r in water_hazards)
                    if in_water:
                        for _ in range(40):
                            particles.append({
                                'x': sim_x + random.uniform(-0.2, 0.2), 'y': sim_y + random.uniform(-0.2, 0.2), 'z': 0,
                                'vx': random.uniform(-0.5, 0.5), 'vy': random.uniform(-0.5, 0.5), 'vz': random.uniform(1.0, 4.0),
                                'life': random.randint(20, 40),
                                'color': (200, 220, 255)
                            })
                        ball.putt_vx = ball.putt_vy = ball.putt_z = ball.putt_vz = 0
                        ball.is_moving = False
                        ball.strokes += 1
                        ball.x, ball.y = ball.prev_x, ball.prev_y
                        ball.putt_x = curr_w // 2 + (ball.x - hole_pos[0]) * PPU
                        ball.putt_y = curr_h // 2 + (hole_pos[1] - ball.y) * PPU
                        msg_text = "WATER HAZARD! +1 STROKE"
                        msg_timer = 180
                    else:
                        in_bunker = any(math.hypot(sim_x - bx, sim_y - by) < br for bx, by, br, _ in bunkers)
                        if in_bunker:
                            ball.putt_vx *= 0.45; ball.putt_vy *= 0.45
                        else:
                            ball.putt_vx *= 0.7 # Fringe/Rough friction
                            ball.putt_vy *= 0.7
            
            is_moving_2d = abs(ball.putt_vx) >= 0.06 or abs(ball.putt_vy) >= 0.06 or ball.putt_z > 0
            
            if ball.putt_x < 0 or ball.putt_x > curr_w or ball.putt_y < 0 or ball.putt_y > curr_h:
                hit_water_fast = False
                while abs(ball.putt_vx) >= 0.06 or abs(ball.putt_vy) >= 0.06 or ball.putt_z > 0:
                    if ball.putt_z > 0 or ball.putt_vz != 0:
                        ball.putt_x += ball.putt_vx
                        ball.putt_y += ball.putt_vy
                        ball.putt_z += ball.putt_vz
                        ball.putt_vz -= 2.3
                        if ball.putt_z <= 0:
                            ball.putt_z = 0; ball.putt_vz = 0
                            sim_x = hole_pos[0] + (ball.putt_x - curr_w//2) / PPU
                            sim_y = hole_pos[1] - (ball.putt_y - curr_h//2) / PPU
                            if any(math.hypot(sim_x - bx, sim_y - by) < br for bx, by, br, _ in bunkers):
                                ball.putt_vx *= 0.1; ball.putt_vy *= 0.1
                            else:
                                roll_factor = max(0.1, 0.4 + (1.0 - (CLUBS[club_idx][3] / 46.0)) * 0.6) if ball.chipping else 0.4
                                ball.putt_vx *= roll_factor; ball.putt_vy *= roll_factor
                    else:
                        ball.putt_x += ball.putt_vx; ball.putt_y += ball.putt_vy
                        sim_x = hole_pos[0] + (ball.putt_x - curr_w//2) / PPU
                        sim_y = hole_pos[1] - (ball.putt_y - curr_h//2) / PPU
                        if is_on_green(sim_x, sim_y, green_center, green_shape):
                            sx, sy = get_slope(sim_x, sim_y, slope_waves, pin_positions)
                            ball.putt_vx += sx * 2.8; ball.putt_vy += sy * 2.8
                            ball.putt_vx *= 0.97; ball.putt_vy *= 0.97
                            if math.hypot(ball.putt_vx, ball.putt_vy) < 0.7 and math.hypot(sx, sy) < 0.02:
                                ball.putt_vx *= 0.5; ball.putt_vy *= 0.5
                        else:
                            in_water = any(math.hypot(sim_x - haz_x, sim_y - haz_y) < haz_r for haz_x, haz_y, haz_r in water_hazards)
                            if in_water:
                                ball.putt_vx = ball.putt_vy = ball.putt_z = ball.putt_vz = 0
                                hit_water_fast = True
                                break
                            
                            in_bunker = any(math.hypot(sim_x - bx, sim_y - by) < br for bx, by, br, _ in bunkers)
                            if in_bunker:
                                ball.putt_vx *= 0.45; ball.putt_vy *= 0.45
                            else:
                                ball.putt_vx *= 0.7; ball.putt_vy *= 0.7
                state = "3D"
                ball.is_moving = False
                ball.putt_vx = ball.putt_vy = ball.putt_z = ball.putt_vz = 0
                ball.z = 0
                
                if hit_water_fast:
                    ball.strokes += 1
                    msg_text = "WATER HAZARD! +1 STROKE"
                    msg_timer = 180
                    ball.x, ball.y = ball.prev_x, ball.prev_y
                else:
                    ball.x = hole_pos[0] + (ball.putt_x - curr_w//2) / PPU
                    ball.y = hole_pos[1] - (ball.putt_y - curr_h//2) / PPU
                closest_x = 0; closest_w = 30; min_dist = 9999
                for y, x, w, *_ in fairway_nodes:
                    if abs(y - ball.y) < min_dist:
                        min_dist = abs(y - ball.y)
                        closest_x = x; closest_w = w
                    if abs(ball.x - closest_x) > 120 or ball.y < -50 or ball.y > hole_pos[1] + 150:
                        ball.x, ball.y = ball.prev_x, ball.prev_y
                        msg_text = "OUT OF BOUNDS! +2 STROKES"
                        msg_timer = 180
                        ball.strokes += 2
                    else:
                        in_bunker = any(math.hypot(ball.x - bx, ball.y - by) < br for bx, by, br, _ in bunkers)
                        if in_bunker:
                            ball.lie = random.randint(15, 85)
                        elif abs(ball.x - closest_x) <= closest_w:
                            ball.lie = 100
                        else:
                            ball.lie = random.randint(30, 100)
                ball.chipping = False
                aim_angle = math.degrees(math.atan2(hole_pos[0] - ball.x, hole_pos[1] - ball.y))
                cam_angle = aim_angle
                is_moving_2d = False
                was_moving_2d = False

            if not is_moving_2d and was_moving_2d:
                ball.putt_vx = ball.putt_vy = ball.putt_z = 0
                sim_x = hole_pos[0] + (ball.putt_x - curr_w//2) / PPU
                sim_y = hole_pos[1] - (ball.putt_y - curr_h//2) / PPU
                if is_on_green(sim_x, sim_y, green_center, green_shape):
                    ball.lie = 100
                    ball.chipping = False
                else:
                    in_bunker = any(math.hypot(sim_x - bx, sim_y - by) < br for bx, by, br, _ in bunkers)
                    if in_bunker:
                        ball.lie = random.randint(15, 85)
                        ball.chipping = True
                    else:
                        ball.lie = random.randint(30, 90)
                        ball.chipping = True if ball.lie < 70 else False
            elif not is_moving_2d:
                ball.putt_vx = ball.putt_vy = ball.putt_z = 0
                
            # Physics around the hole
            if ball.putt_z == 0:
                hole_cx, hole_cy = curr_w // 2, curr_h // 2
                dist_to_hole = math.hypot(ball.putt_x - hole_cx, ball.putt_y - hole_cy)
                speed = math.hypot(ball.putt_vx, ball.putt_vy)
                
                if 0 < dist_to_hole < 24:
                    # Gentle pull only when right on the lip
                    pull_strength = (24 - dist_to_hole) * 0.08
                    ball.putt_vx += ((hole_cx - ball.putt_x) / dist_to_hole) * pull_strength
                    ball.putt_vy += ((hole_cy - ball.putt_y) / dist_to_hole) * pull_strength
                    
                    if dist_to_hole < 12 and speed < 14.0:
                        state = "HOLE"
                        scores[hole_idx] = ball.strokes
                        show_scorecard = True
                    elif dist_to_hole < 17 and speed >= 14.0:
                        # Lip out penalty - lose speed from hitting the edge
                        ball.putt_vx *= 0.85
                        ball.putt_vy *= 0.85

        # --- Rendering ---
        if state == "3D":
            # Infinite Rough background (prevents polygon near-plane stretching entirely)
            pygame.draw.rect(screen, selected_course.rough_color, (0, int(curr_h*0.38), curr_w, curr_h))

            # --- Panorama (Skyline & Lake) ---
            horizon = int(curr_h * 0.38)
            fov = 75.0 # View angle width in degrees
            deg_to_px = curr_w / fov
            pano_w = int(360 * deg_to_px)
            ca = cam_angle % 360
            offset_x = - (ca * deg_to_px) + (curr_w / 2)

            # Draw Water Horizon (skipped for Desert and NYC Themes)
            if selected_course.theme not in ["Desert", "NYC"]:
                lake_h = max(5, int(curr_h * 0.015))
                for shift in [0, pano_w, -pano_w]:
                    rx = offset_x + shift
                    lx = int(rx)
                    lw = int(180 * deg_to_px)
                    if lx + lw > 0 and lx < curr_w:
                        pygame.draw.rect(screen, (40, 100, 160), (lx, horizon - lake_h, lw, lake_h))
                        pygame.draw.line(screen, (194, 178, 128), (lx, horizon), (lx + lw, horizon), 2)
            
            # Draw Skyline
            for b in selected_course.skyline:
                if isinstance(b[0], str):
                    b_type = b[0]
                    x1 = b[1] * deg_to_px
                    w_px = max(2, int(b[2] * deg_to_px))
                    h_px = int(b[3] * (curr_h / 720.0))
                    color = tuple(b[4])
                    extra = b[5] if len(b) > 5 else None
                else: # Fallback for old schema
                    b_type = "rect"
                    x1 = b[0] * deg_to_px
                    w_px = max(2, int(b[1] * deg_to_px))
                    h_px = int(b[2] * (curr_h / 720.0))
                    color = tuple(b[3])
                    extra = b[4] if len(b) > 4 else None
                
                for shift in [0, pano_w, -pano_w]:
                    rx = offset_x + x1 + shift
                    if rx + w_px > 0 and rx < curr_w:
                        if b_type == "rect":
                            pygame.draw.rect(screen, color, (int(rx), horizon - h_px, w_px, h_px))
                            if extra == "SEARS":
                                pygame.draw.line(screen, (0,0,0), (int(rx + w_px*0.25), horizon - h_px), (int(rx + w_px*0.25), horizon - h_px - 35), 2)
                                pygame.draw.line(screen, (0,0,0), (int(rx + w_px*0.75), horizon - h_px), (int(rx + w_px*0.75), horizon - h_px - 35), 2)
                            elif extra == "HANCOCK":
                                pygame.draw.line(screen, (0,0,0), (int(rx + w_px*0.35), horizon - h_px), (int(rx + w_px*0.35), horizon - h_px - 25), 2)
                                pygame.draw.line(screen, (0,0,0), (int(rx + w_px*0.65), horizon - h_px), (int(rx + w_px*0.65), horizon - h_px - 25), 2)
                                pygame.draw.line(screen, (10,10,10), (int(rx), horizon - h_px), (int(rx + w_px), horizon - h_px + 40), 1)
                                pygame.draw.line(screen, (10,10,10), (int(rx + w_px), horizon - h_px), (int(rx), horizon - h_px + 40), 1)
                        elif b_type in ["mountain", "tree"]:
                            pts = [(int(rx), horizon), (int(rx + w_px/2), horizon - h_px), (int(rx + w_px), horizon)]
                            pygame.draw.polygon(screen, color, pts)

            # --- OB Stakes (White Posts) ---
            for i, node in enumerate(fairway_nodes):
                if i % 2 == 0:  # Every 40 yards
                    y, x, w = node[0], node[1], node[2]
                    for sx in [x - 120, x + 120]:
                        stake_z = get_elevation(sx, y, fairway_nodes, green_z)
                        base = project(sx, y, stake_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
                        if base and base[3] > -14:
                            top = project(sx, y, stake_z + 1.5, cam_x, cam_y, cam_angle, curr_w, curr_h)
                            if top:
                                pygame.draw.line(screen, WHITE, base[:2], top[:2], max(1, int(2.5*base[2])))
            
            # OB Stakes behind Green
            for sx in range(int(hole_pos[0]) - 80, int(hole_pos[0]) + 81, 20):
                stake_z = get_elevation(sx, hole_pos[1] + 50, fairway_nodes, green_z)
                base = project(sx, hole_pos[1] + 50, stake_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if base and base[3] > -14:
                    top = project(sx, hole_pos[1] + 50, stake_z + 1.5, cam_x, cam_y, cam_angle, curr_w, curr_h)
                    if top:
                        pygame.draw.line(screen, WHITE, base[:2], top[:2], max(1, int(2.5*base[2])))
                        
            # OB Stakes behind Tee
            for sx in range(-80, 81, 20):
                stake_z = get_elevation(sx, -50, fairway_nodes, green_z)
                base = project(sx, -50, stake_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if base and base[3] > -14:
                    top = project(sx, -50, stake_z + 1.5, cam_x, cam_y, cam_angle, curr_w, curr_h)
                    if top:
                        pygame.draw.line(screen, WHITE, base[:2], top[:2], max(1, int(2.5*base[2])))

            for i in range(len(fairway_nodes)-1):
                node1 = fairway_nodes[i]
                node2 = fairway_nodes[i+1]
                y1, x1, w1, z1 = node1[:4]
                cs1 = node1[4] if len(node1) > 4 else 0.0
                y2, x2, w2, z2 = node2[:4]
                cs2 = node2[4] if len(node2) > 4 else 0.0
                
                p1l = project(x1-w1, y1, z1 - cs1*w1, cam_x, cam_y, cam_angle, curr_w, curr_h)
                p1r = project(x1+w1, y1, z1 + cs1*w1, cam_x, cam_y, cam_angle, curr_w, curr_h)
                p2l = project(x2-w2, y2, z2 - cs2*w2, cam_x, cam_y, cam_angle, curr_w, curr_h)
                p2r = project(x2+w2, y2, z2 + cs2*w2, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if p1l and p1r and p2l and p2r:
                    if p1l[3] > -14 or p2l[3] > -14 or p1r[3] > -14 or p2r[3] > -14:
                        pygame.draw.polygon(screen, FAIRWAY, [p1l[:2], p1r[:2], p2r[:2], p2l[:2]])

            # --- Draw Bunkers ---
            for bx, by, br, bz in bunkers:
                b_pts = []
                for a in range(0, 360, 20):
                    rad = math.radians(a)
                    r_dist = br + math.sin(a * 2.5) * (br * 0.15)
                    pt = project(bx + math.cos(rad)*r_dist, by + math.sin(rad)*r_dist, bz, cam_x, cam_y, cam_angle, curr_w, curr_h)
                    if pt: b_pts.append(pt)
                if len(b_pts) > 2 and any(pt[3] > -14 for pt in b_pts):
                    pygame.draw.polygon(screen, (210, 180, 140), [pt[:2] for pt in b_pts])

            # --- Draw Water Hazards ---
            for haz_x, haz_y, haz_r in water_hazards:
                w_pts = []
                for a in range(0, 360, 20):
                    rad = math.radians(a)
                    r_dist = haz_r + math.sin(a * 3) * (haz_r * 0.1)
                    wz = get_elevation(haz_x + math.cos(rad)*r_dist, haz_y + math.sin(rad)*r_dist, fairway_nodes, green_z) - 0.5
                    pt = project(haz_x + math.cos(rad)*r_dist, haz_y + math.sin(rad)*r_dist, wz, cam_x, cam_y, cam_angle, curr_w, curr_h)
                    if pt: w_pts.append(pt)
                if len(w_pts) > 2 and any(pt[3] > -14 for pt in w_pts):
                    pygame.draw.polygon(screen, (40, 100, 160), [pt[:2] for pt in w_pts])
                    pygame.draw.polygon(screen, (200, 200, 255), [pt[:2] for pt in w_pts], max(1, int(w_pts[0][2])))

            # --- Tee Box ---
            tb_z1 = get_elevation(0, -10, fairway_nodes, green_z)
            tb_z2 = get_elevation(0, 8, fairway_nodes, green_z)
            tb_p1l = project(-12, -10, tb_z1, cam_x, cam_y, cam_angle, curr_w, curr_h)
            tb_p1r = project(12, -10, tb_z1, cam_x, cam_y, cam_angle, curr_w, curr_h)
            tb_p2l = project(-12, 8, tb_z2, cam_x, cam_y, cam_angle, curr_w, curr_h)
            tb_p2r = project(12, 8, tb_z2, cam_x, cam_y, cam_angle, curr_w, curr_h)
            if tb_p1l and tb_p1r and tb_p2l and tb_p2r:
                if tb_p1l[3] > -14 or tb_p2l[3] > -14 or tb_p1r[3] > -14 or tb_p2r[3] > -14:
                    pygame.draw.polygon(screen, GREEN_COLOR, [tb_p1l[:2], tb_p1r[:2], tb_p2r[:2], tb_p2l[:2]])
                    pygame.draw.polygon(screen, WHITE, [tb_p1l[:2], tb_p1r[:2], tb_p2r[:2], tb_p2l[:2]], 1)
                
            tm_z = get_elevation(0, 0, fairway_nodes, green_z)
            tm1 = project(-4, 0, tm_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
            tm2 = project(4, 0, tm_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
            if tm1 and tm1[3] > -14: 
                pygame.draw.circle(screen, RED, tm1[:2], max(1, int(0.2*tm1[2])))
                pygame.draw.circle(screen, WHITE, tm1[:2], max(1, int(0.2*tm1[2])), 1)
            if tm2 and tm2[3] > -14: 
                pygame.draw.circle(screen, RED, tm2[:2], max(1, int(0.2*tm2[2])))
                pygame.draw.circle(screen, WHITE, tm2[:2], max(1, int(0.2*tm2[2])), 1)

            # Draw Green shape (matches 2D view)
            green1_pts = []
            green2_pts = []
            g1_w, g1_h = green_shape[0]
            g2_w, g2_h = green_shape[1]
            ox, oy = green_shape[2]
            for a in range(0, 360, 10):
                rad = math.radians(a)
                gp1 = project(green_center[0] + math.cos(rad)*g1_w, green_center[1] + math.sin(rad)*g1_h, green_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if gp1: green1_pts.append(gp1)
                gp2 = project(green_center[0] + ox + math.cos(rad)*g2_w, green_center[1] + oy + math.sin(rad)*g2_h, green_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if gp2: green2_pts.append(gp2)
            if len(green1_pts) > 2 and any(pt[3] > -14 for pt in green1_pts): pygame.draw.polygon(screen, GREEN_COLOR, [pt[:2] for pt in green1_pts])
            if len(green2_pts) > 2 and any(pt[3] > -14 for pt in green2_pts): pygame.draw.polygon(screen, GREEN_COLOR, [pt[:2] for pt in green2_pts])

            f = project(hole_pos[0], hole_pos[1], green_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
            if f and f[3] > -14:
                pygame.draw.line(screen, WHITE, (f[0], f[1]), (f[0], f[1]-max(1, int(12*f[2]))), 2)
                pygame.draw.rect(screen, RED, (f[0], f[1]-max(1, int(12*f[2])), max(1, int(4*f[2])), max(1, int(3*f[2]))))
            
            # --- Draw Trees ---
            trees_to_draw = []
            for tree_data in trees:
                tx, ty, tz, th, tw = tree_data[:5]
                t_color = tree_data[5] if len(tree_data) > 5 else (15, 55, 30)
                t_type = tree_data[6] if len(tree_data) > 6 else "tree"
                t_extra = tree_data[7] if len(tree_data) > 7 else None
                dist = math.hypot(tx - cam_x, ty - cam_y)
                trees_to_draw.append((dist, tx, ty, tz, th, tw, t_color, t_type, t_extra))
            
            trees_to_draw.sort(key=lambda x: x[0], reverse=True) # Farthest first
            
            for dist, tx, ty, tz, th, tw, t_color, t_type, t_extra in trees_to_draw:
                base = project(tx, ty, tz, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if base and base[3] > -14:
                    if t_type == "tree":
                        top = project(tx, ty, tz + th, cam_x, cam_y, cam_angle, curr_w, curr_h)
                        l_bot = project(tx, ty, tz + th * 0.3, cam_x, cam_y, cam_angle, curr_w, curr_h)
                        if top and l_bot:
                            trunk_w = max(1, int(tw * 0.3 * base[2]))
                            pygame.draw.line(screen, BROWN, base[:2], l_bot[:2], trunk_w)
                            r1 = max(2, int(tw * 1.2 * l_bot[2]))
                            pygame.draw.circle(screen, t_color, l_bot[:2], r1)
                            mid_y = (top[1] + l_bot[1]) // 2
                            mid_x = (top[0] + l_bot[0]) // 2
                            r2 = max(2, int(tw * 0.9 * ((top[2]+l_bot[2])/2)))
                            c_mid = (min(255, t_color[0]+5), min(255, t_color[1]+20), min(255, t_color[2]+10))
                            pygame.draw.circle(screen, c_mid, (mid_x, mid_y), r2)
                            r3 = max(2, int(tw * 0.5 * top[2]))
                            c_top = (min(255, t_color[0]+10), min(255, t_color[1]+40), min(255, t_color[2]+20))
                            pygame.draw.circle(screen, c_top, top[:2], r3)
                    elif t_type == "azalea":
                        top = project(tx, ty, tz + th, cam_x, cam_y, cam_angle, curr_w, curr_h)
                        if top:
                            r1 = max(2, int(tw * base[2]))
                            pygame.draw.circle(screen, t_color, base[:2], r1)
                            c_top = (min(255, t_color[0]+30), min(255, t_color[1]+30), min(255, t_color[2]+30))
                            pygame.draw.circle(screen, c_top, top[:2], max(2, int(tw * 0.7 * top[2])))
                    elif t_type == "bridge":
                        rad = math.radians(t_extra if t_extra else 0)
                        dx = math.cos(rad) * tw / 2
                        dy = math.sin(rad) * tw / 2
                        p1 = project(tx - dx, ty - dy, tz, cam_x, cam_y, cam_angle, curr_w, curr_h)
                        p2 = project(tx + dx, ty + dy, tz, cam_x, cam_y, cam_angle, curr_w, curr_h)
                        pm = project(tx, ty, tz + th, cam_x, cam_y, cam_angle, curr_w, curr_h)
                        if p1 and p2 and pm and all(p[3] > -14 for p in [p1, p2, pm]):
                            pygame.draw.line(screen, t_color, p1[:2], pm[:2], max(2, int(6*pm[2])))
                            pygame.draw.line(screen, t_color, pm[:2], p2[:2], max(2, int(6*pm[2])))
                            pygame.draw.line(screen, (40, 120, 40), p1[:2], pm[:2], max(1, int(3*pm[2])))
                            pygame.draw.line(screen, (40, 120, 40), pm[:2], p2[:2], max(1, int(3*pm[2])))
                            p1_r = project(tx - dx, ty - dy, tz + 1.2, cam_x, cam_y, cam_angle, curr_w, curr_h)
                            p2_r = project(tx + dx, ty + dy, tz + 1.2, cam_x, cam_y, cam_angle, curr_w, curr_h)
                            pm_r = project(tx, ty, tz + th + 1.2, cam_x, cam_y, cam_angle, curr_w, curr_h)
                            if p1_r and p2_r and pm_r:
                                rail_color = (180, 180, 180)
                                pygame.draw.line(screen, rail_color, p1_r[:2], pm_r[:2], max(1, int(1.5*pm[2])))
                                pygame.draw.line(screen, rail_color, pm_r[:2], p2_r[:2], max(1, int(1.5*pm[2])))
                                for frac in [0.0, 0.25, 0.5, 0.75, 1.0]:
                                    bx = (tx - dx) + (dx * 2) * frac
                                    by = (ty - dy) + (dy * 2) * frac
                                    bz_base = tz + th * (frac * 2) if frac <= 0.5 else tz + th * ((1.0 - frac) * 2)
                                    bp = project(bx, by, bz_base, cam_x, cam_y, cam_angle, curr_w, curr_h)
                                    bp_r = project(bx, by, bz_base + 1.2, cam_x, cam_y, cam_angle, curr_w, curr_h)
                                    if bp and bp_r:
                                        pygame.draw.line(screen, rail_color, bp[:2], bp_r[:2], max(1, int(1.5*bp[2])))

            # --- Draw Player ---
            if not ball.is_moving:
                p_angle = math.radians(aim_angle - 90)
                px = ball.x + 2.5 * math.sin(p_angle)
                py = ball.y + 2.5 * math.cos(p_angle)
                p_z = get_elevation(px, py, fairway_nodes, green_z)
                
                feet_l = project(px - 1.0*math.cos(p_angle), py + 1.0*math.sin(p_angle), p_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
                feet_r = project(px + 1.0*math.cos(p_angle), py - 1.0*math.sin(p_angle), p_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
                waist = project(px, py, p_z + 2.5, cam_x, cam_y, cam_angle, curr_w, curr_h)
                neck = project(px, py, p_z + 4.5, cam_x, cam_y, cam_angle, curr_w, curr_h)
                head = project(px, py, p_z + 5.5, cam_x, cam_y, cam_angle, curr_w, curr_h)
                
                if head and waist and feet_l and feet_r and neck and waist[3] > -14:
                    PLAYER_COLOR = (200, 220, 255)
                    pygame.draw.line(screen, (50, 50, 50), waist[:2], feet_l[:2], 2)
                    pygame.draw.line(screen, (50, 50, 50), waist[:2], feet_r[:2], 2)
                    pygame.draw.line(screen, PLAYER_COLOR, waist[:2], neck[:2], 4)
                    pygame.draw.circle(screen, (255, 200, 150), head[:2], max(2, int(1.0 * head[2])))
                    
                    if is_swinging:
                        swing_rot = math.radians(aim_angle + 160 * power)
                        club_x = px + 3.5 * math.sin(swing_rot)
                        club_y = py + 3.5 * math.cos(swing_rot)
                        club_z = p_z + 6 * power
                        hands_x = px + 1.5 * math.sin(swing_rot)
                        hands_y = py + 1.5 * math.cos(swing_rot)
                        hands_z = p_z + 2.5 + 2 * power
                    else:
                        club_x, club_y, club_z = ball.x, ball.y, get_elevation(ball.x, ball.y, fairway_nodes, green_z)
                        aim_rad = math.radians(aim_angle)
                        hands_x = px + 1.5 * math.sin(aim_rad)
                        hands_y = py + 1.5 * math.cos(aim_rad)
                        hands_z = p_z + 2.0

                    hands = project(hands_x, hands_y, hands_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
                    club_head = project(club_x, club_y, club_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
                    
                    if hands and club_head:
                        pygame.draw.line(screen, PLAYER_COLOR, neck[:2], hands[:2], 2)
                        pygame.draw.line(screen, (150, 150, 150), hands[:2], club_head[:2], 2)
                        
                        cw = max(1, int((1.0 - club_idx * 0.04) * club_head[2]))
                        ch = max(1, int((0.8 if club_idx <= 2 else 0.25) * club_head[2]))
                        club_rect = pygame.Rect(club_head[0]-cw, club_head[1]-ch, cw*2, ch*2)
                        pygame.draw.ellipse(screen, (100, 100, 100), club_rect)
                        
            # --- Draw Peers in 3D ---
            for p_id, p_state in active_peers:
                if p_state['hole'] == hole_idx and p_state['state'] == "3D":
                    p_ground_z = get_elevation(p_state['x'], p_state['y'], fairway_nodes, green_z)
                    p_b = project(p_state['x'], p_state['y'], p_state['z'] + p_ground_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
                    if p_b and p_b[3] > -14:
                        pygame.draw.circle(screen, (255, 100, 100), (p_b[0], p_b[1]), max(1, int(0.15*p_b[2])))
                        screen.blit(font_small.render(p_id, True, (255, 150, 150)), (p_b[0] + 10, p_b[1] - 10))

            b_ground_z = get_elevation(ball.x, ball.y, fairway_nodes, green_z)
            b = project(ball.x, ball.y, ball.z + b_ground_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
            if b and b[3] > -14: pygame.draw.circle(screen, WHITE, (b[0], b[1]), max(1, int(0.15*b[2])))
            
            # --- Draw Particles (3D) ---
            for p in particles:
                p_ground_z = get_elevation(p['x'], p['y'], fairway_nodes, green_z)
                p_proj = project(p['x'], p['y'], p['z'] + p_ground_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if p_proj and p_proj[3] > -14:
                    pygame.draw.circle(screen, p['color'], p_proj[:2], max(1, int(0.1*p_proj[2])))

            # --- Aim Indicator ---
            if not ball.is_moving:
                lie_mult = ball.lie / 100.0
                adj_dist = (CLUBS[club_idx][1] - (trajectory_offset * 2.5)) * lie_mult
                adj_height = (CLUBS[club_idx][2] + (trajectory_offset * 1.5)) * lie_mult
                
                # Predict RPM for the shot
                _, _, _, preview_rpm = calculate_trackman_stats(club_idx, trajectory_offset, lie_mult)
                start_angle = aim_angle + (face_angle * 0.85)
                spin_axis = face_angle * 4.0
                
                # Apply Aerodynamic Wind & Spin to the preview
                adj_dist, adj_height, lat_wx, lat_wy = apply_wind_physics(adj_dist, adj_height, start_angle, wx, wy, preview_rpm)
                
                spin_eff = math.cos(math.radians(spin_axis))
                adj_dist *= max(0.7, spin_eff)
                
                # Adjust for Elevation Predictively
                start_elev = get_elevation(ball.x, ball.y, fairway_nodes, green_z)
                target_x_est = ball.x + adj_dist * math.sin(math.radians(start_angle))
                target_y_est = ball.y + adj_dist * math.cos(math.radians(start_angle))
                target_elev = get_elevation(target_x_est, target_y_est, fairway_nodes, green_z)
                elev_diff = target_elev - start_elev
                adj_dist -= elev_diff * 1.0
                adj_dist = max(0.1, adj_dist)
                
                base_target_x = ball.x + adj_dist * math.sin(math.radians(start_angle))
                base_target_y = ball.y + adj_dist * math.cos(math.radians(start_angle))
                
                arc_points = []
                sim_x, sim_y = ball.x, ball.y
                sim_vx = (base_target_x - ball.x) / 100.0
                sim_vy = (base_target_y - ball.y) / 100.0
                sim_wx = (lat_wx / 60.0) if show_wind_preview else 0.0
                sim_wy = (lat_wy / 60.0) if show_wind_preview else 0.0
                
                sim_cdx = math.cos(math.radians(start_angle))
                sim_cdy = -math.sin(math.radians(start_angle))
                sim_caccel = face_angle * 0.001 * (preview_rpm / 2000.0)
                
                sim_start_z = get_elevation(ball.x, ball.y, fairway_nodes, green_z)
                sim_elev_diff = target_elev - sim_start_z
                
                for step in range(101):
                    t = step / 100.0
                    absolute_z = sim_start_z + 4 * adj_height * t * (1 - t) + (sim_elev_diff * t)
                    
                    sim_vx += sim_cdx * sim_caccel
                    sim_vy += sim_cdy * sim_caccel
                    
                    alt_wind_mult = max(0, absolute_z - sim_start_z) / 40.0
                    sim_x += sim_vx + (sim_wx * alt_wind_mult)
                    sim_y += sim_vy + (sim_wy * alt_wind_mult)
                    
                    if step % 6 == 0 or step == 100:
                        proj_pt = project(sim_x, sim_y, absolute_z, cam_x, cam_y, cam_angle, curr_w, curr_h)
                        if proj_pt and proj_pt[3] > -14:
                            arc_points.append(proj_pt[:2])
                            
                t_proj = project(sim_x, sim_y, get_elevation(sim_x, sim_y, fairway_nodes, green_z), cam_x, cam_y, cam_angle, curr_w, curr_h)
                        
                if len(arc_points) > 1:
                    pygame.draw.lines(screen, YELLOW, False, arc_points, 1)

                if b and t_proj and t_proj[3] > -14:
                    pygame.draw.circle(screen, YELLOW, (t_proj[0], t_proj[1]), max(2, int(15*t_proj[2])), 1)

            if is_stat_3d:
                controls_txt = "ARROWS: Aim/Loft  |  A/D: Face Angle  |  W/S: Change Club  |  SPACE: Swing"
                screen.blit(font_small.render(controls_txt, True, WHITE), (20, curr_h - 30))

            if not my_turn and state == "3D" and ball.strokes == 0:
                wait_txt = font_med.render(f"Waiting for {waiting_on} to Tee Off...", True, YELLOW)
                screen.blit(wait_txt, (curr_w//2 - wait_txt.get_width()//2, 100))

            draw_hud(screen, curr_w, curr_h, ball, hole_pos, club_idx, power, wx, wy, is_swinging, trajectory_offset, face_angle, cam_angle, hole_idx, par, show_adv_stats, active_peers, network.player_id)

        elif state == "GREEN":
            hole_radius = max(6, int(curr_h * 0.012))
            ball_radius = max(3, int(curr_h * 0.006))
            
            screen.fill(selected_course.rough_color)
            g1_w, g1_h = green_shape[0]
            g2_w, g2_h = green_shape[1]
            ox, oy = green_shape[2]
            
            green_cx = curr_w//2 + int((green_center[0] - hole_pos[0]) * PPU)
            green_cy = curr_h//2 - int((green_center[1] - hole_pos[1]) * PPU)
            pygame.draw.ellipse(screen, GREEN_COLOR, pygame.Rect(green_cx - int(g1_w*PPU), green_cy - int(g1_h*PPU), int(g1_w*PPU*2), int(g1_h*PPU*2)))
            pygame.draw.ellipse(screen, GREEN_COLOR, pygame.Rect(green_cx + int(ox*PPU) - int(g2_w*PPU), green_cy - int(oy*PPU) - int(g2_h*PPU), int(g2_w*PPU*2), int(g2_h*PPU*2)))
            
            # --- Draw Bunkers in 2D ---
            for bx, by, br, bz in bunkers:
                screen_bx = curr_w//2 + int((bx - hole_pos[0]) * PPU)
                screen_by = curr_h//2 - int((by - hole_pos[1]) * PPU)
                screen_br = int(br * PPU)
                
                if -screen_br < screen_bx < curr_w + screen_br and -screen_br < screen_by < curr_h + screen_br:
                    b_pts = []
                    for a in range(0, 360, 20):
                        rad = math.radians(a)
                        r_dist = screen_br + math.sin(a * 2.5) * (screen_br * 0.15)
                        b_pts.append((screen_bx + math.cos(rad)*r_dist, screen_by + math.sin(rad)*r_dist))
                    if len(b_pts) > 2:
                        pygame.draw.polygon(screen, (210, 180, 140), b_pts)

            # --- Draw Water Hazards in 2D ---
            for haz_x, haz_y, haz_r in water_hazards:
                screen_wx = curr_w//2 + int((haz_x - hole_pos[0]) * PPU)
                screen_wy = curr_h//2 - int((haz_y - hole_pos[1]) * PPU)
                screen_wr = int(haz_r * PPU)
                
                if -screen_wr < screen_wx < curr_w + screen_wr and -screen_wr < screen_wy < curr_h + screen_wr:
                    w_pts = []
                    for a in range(0, 360, 20):
                        rad = math.radians(a)
                        r_dist = screen_wr + math.sin(a * 3) * (screen_wr * 0.1)
                        w_pts.append((screen_wx + math.cos(rad)*r_dist, screen_wy + math.sin(rad)*r_dist))
                    if len(w_pts) > 2:
                        pygame.draw.polygon(screen, (40, 100, 160), w_pts)
                        pygame.draw.polygon(screen, (200, 200, 255), w_pts, 2)

            # Draw slope grid
            for gy in range(0, curr_h + 70, 70):
                for gx in range(0, curr_w + 70, 70):
                    sim_x = hole_pos[0] + (gx - curr_w//2) / PPU
                    sim_y = hole_pos[1] - (gy - curr_h//2) / PPU
                    if is_on_green(sim_x, sim_y, green_center, green_shape):
                        sx, sy = get_slope(sim_x, sim_y, slope_waves, pin_positions)
                        draw_sx = sx * 4500
                        draw_sy = sy * 4500
                        if abs(draw_sx) > 1 or abs(draw_sy) > 1:
                            pygame.draw.line(screen, (35, 140, 35), (gx, gy), (gx + draw_sx, gy + draw_sy), 2)
                            pygame.draw.circle(screen, (200, 255, 200), (int(gx + draw_sx), int(gy + draw_sy)), 2)

            hole_screen_pos = (curr_w//2, curr_h//2)
            pygame.draw.circle(screen, HOLE_COLOR, hole_screen_pos, hole_radius)
            
            # --- FIXED: Putter Line ---
            if ball.is_dragging:
                mods = pygame.key.get_mods()
                power_boost = 3.0 if mods & pygame.KMOD_SHIFT else 1.0
                line_color = YELLOW if power_boost > 1.0 else WHITE
                
                # Line pulling back from the ball (Slingshot to mouse)
                pygame.draw.line(screen, line_color, (int(ball.putt_x), int(ball.putt_y - ball.putt_z)), mouse_pos, 2)

            if ball.putt_z > 0:
                pygame.draw.circle(screen, (0, 0, 0), (int(ball.putt_x), int(ball.putt_y)), ball_radius) # shadow
            pygame.draw.circle(screen, WHITE, (int(ball.putt_x), int(ball.putt_y - ball.putt_z)), ball_radius)
            
            # --- Draw Peers in 2D ---
            for p_id, p_state in active_peers:
                if p_state['hole'] == hole_idx and p_state['state'] == "GREEN":
                    px, py, pz = int(p_state['putt_x']), int(p_state['putt_y']), p_state['putt_z']
                    if pz > 0: pygame.draw.circle(screen, (0, 0, 0), (px, py), ball_radius)
                    pygame.draw.circle(screen, (255, 100, 100), (px, int(py - pz)), ball_radius)
                    screen.blit(font_small.render(p_id, True, (255, 150, 150)), (px + 10, py - 20))
            
            # --- Draw Particles (2D) ---
            for p in particles:
                screen_px = curr_w//2 + int((p['x'] - hole_pos[0]) * PPU)
                screen_py = curr_h//2 - int((p['y'] - hole_pos[1]) * PPU)
                pz_screen = int(p['z'] * PPU)
                if pz_screen > 0:
                    pygame.draw.circle(screen, p['color'], (screen_px, screen_py - pz_screen), max(1, int(p['life']/10)))
                    
            mode_str = f"CHIP ({CLUBS[club_idx][0]})" if ball.chipping else "PUTT"
            lie_str = f"Lie: {ball.lie}%"
            color = WHITE if ball.lie >= 90 else YELLOW
            txt = f"{mode_str} - {lie_str} - Drag to aim. SHIFT: Power. SPACE: mode. W/S: club."
            screen.blit(font_med.render(txt, True, color), (40, 40))

        elif state == "HOLE":
            screen.fill((0, 0, 0))
            diff = ball.strokes - par
            
            if ball.strokes == 1: score_str = "Hole in One!!!"
            elif diff <= -3: score_str = "Albatross!"
            elif diff == -2: score_str = "Eagle!"
            elif diff == -1: score_str = "Birdie"
            elif diff == 0: score_str = "Par"
            elif diff == 1: score_str = "Bogey"
            elif diff == 2: score_str = "Double Bogey"
            elif diff == 3: score_str = "Triple Bogey"
            else: score_str = f"+{diff}"

            msg1 = font_large.render(f"HOLE {hole_idx+1} FINISHED! PAR {par}", True, WHITE)
            msg2 = font_large.render(f"SCORE: {ball.strokes} ({score_str})", True, YELLOW)
            msg3 = font_med.render(f"TOTAL STROKES: {sum(s for s in scores if s is not None)}", True, WHITE)
            screen.blit(msg1, (curr_w//2 - msg1.get_width()//2, curr_h//2 - 60))
            screen.blit(msg2, (curr_w//2 - msg2.get_width()//2, curr_h//2 - 10))
            screen.blit(msg3, (curr_w//2 - msg3.get_width()//2, curr_h//2 + 40))
            
            if waiting_for_others:
                msg_restart = font_med.render("Waiting for Group to Finish...", True, YELLOW)
            else:
                msg_restart = font_med.render("Press SPACE for Next Hole", True, WHITE)
            screen.blit(msg_restart, (curr_w//2 - msg_restart.get_width()//2, curr_h//2 + 100))

        # Check for hole jump action
        if jump_hole_dir != 0:
            hole_idx = (hole_idx + jump_hole_dir) % len(selected_course.holes)
            hole_data = selected_course.holes[hole_idx]
            green_center = hole_data["hole_pos"]
            pin_positions = hole_data.get("pin_positions", [green_center])
            
            wind_rng = random.Random(312 + hole_idx)
            wx, wy = wind_rng.uniform(-difficulty, difficulty), wind_rng.uniform(-difficulty, difficulty)
            pin_idx = wind_rng.randint(0, len(pin_positions) - 1)
            hole_pos = pin_positions[pin_idx]
            
            fairway_nodes = hole_data["fairway"]
            par = hole_data["par"]
            green_shape = hole_data["green"]
            slope_waves = hole_data["slope_waves"]
            green_z = hole_data["green_z"]
            bunkers = hole_data["bunkers"]
            water_hazards = hole_data.get("water", [])
            trees = hole_data["trees"]
            ball = Ball()
            cam_x, cam_y = 0, -20
            aim_angle = math.degrees(math.atan2(hole_pos[0], hole_pos[1]))
            cam_angle = aim_angle
            trajectory_offset = 0.0
            face_angle = 0.0
            state = "3D"
            is_swinging = False; power = 0.0
            jump_hole_dir = 0
            show_scorecard = False

        # Check for unplayable lie action
        if take_unplayable:
            take_unplayable = False
            if not ball.is_moving and ball.strokes > 0 and state != "HOLE":
                rx, ry = None, None
                # Spiral search outward to find nearest point of relief
                for radius in range(2, 30, 2):
                    for angle in range(0, 360, 30):
                        rad = math.radians(angle)
                        test_x = ball.x + math.cos(rad) * radius
                        test_y = ball.y + math.sin(rad) * radius
                        
                        dist_to_hole = math.hypot(ball.x - hole_pos[0], ball.y - hole_pos[1])
                        new_dist = math.hypot(test_x - hole_pos[0], test_y - hole_pos[1])
                        if new_dist < dist_to_hole: continue # Cannot drop closer to the hole
                        
                        hit_tree = any(math.hypot(test_x - t[0], test_y - t[1]) < t[4] * 0.8 for t in trees)
                        if hit_tree: continue
                        hit_water = any(math.hypot(test_x - haz_x, test_y - haz_y) < haz_r for haz_x, haz_y, haz_r in water_hazards)
                        if hit_water: continue
                        
                        closest_x = 0; min_dist = 9999
                        for node in fairway_nodes:
                            if abs(node[0] - test_y) < min_dist:
                                min_dist = abs(node[0] - test_y)
                                closest_x = node[1]
                        if abs(test_x - closest_x) > 120 or test_y < -50 or test_y > hole_pos[1] + 50:
                            continue # Out of Bounds
                            
                        rx, ry = test_x, test_y
                        break
                    if rx is not None: break
                    
                if rx is not None:
                    ball.x, ball.y = rx, ry
                else: # Fallback to previous shot location if hopelessly trapped
                    ball.x, ball.y = ball.prev_x, ball.prev_y
                    
                ball.strokes += 1
                in_bunker = any(math.hypot(ball.x - bx, ball.y - by) < br for bx, by, br, _ in bunkers)
                if in_bunker:
                    ball.lie = random.randint(15, 85)
                else:
                    ball.lie = random.randint(30, 80)
                msg_text = "UNPLAYABLE LIE! +1 STROKE"
                msg_timer = 180
                aim_angle = math.degrees(math.atan2(hole_pos[0] - ball.x, hole_pos[1] - ball.y))
                cam_angle = aim_angle
                state = "3D"
                ball.chipping = False
                ball.putt_vx = ball.putt_vy = ball.putt_z = ball.putt_vz = 0

        if msg_timer > 0:
            msg_timer -= 1
            surf = font_large.render(msg_text, True, RED)
            bg_rect = surf.get_rect(center=(curr_w//2, curr_h//2 - 100)).inflate(20, 20)
            pygame.draw.rect(screen, WHITE, bg_rect, border_radius=8)
            pygame.draw.rect(screen, HOLE_COLOR, bg_rect, 3, border_radius=8)
            screen.blit(surf, surf.get_rect(center=(curr_w//2, curr_h//2 - 100)))

        draw_menus(screen, curr_w, active_menu, show_wind_preview, show_adv_stats)
        
        if show_scorecard:
            group_scores = {network.player_id: scores}
            for p_id, p_state in active_peers:
                if p_id in current_tee_order:
                    if 'scores' in p_state:
                        group_scores[p_id] = p_state['scores']
                    else:
                        p_scores = [None] * 18
                        for h, s in peer_hole_scores.get(p_id, {}).items():
                            p_scores[h] = s
                        group_scores[p_id] = p_scores
                        
            draw_scorecard(screen, curr_w, curr_h, group_scores, selected_course.holes, current_tee_order)

        pygame.display.flip()
        clock.tick(60)
    pygame.quit()

if __name__ == "__main__":
    main()