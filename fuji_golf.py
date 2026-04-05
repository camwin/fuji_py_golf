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
        base_path = os.path.abspath(".")
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

def generate_skyline():
    buildings = []
    random.seed(312) # Chicago area code for a consistent skyline
    # Background layer
    for _ in range(70):
        angle = random.uniform(190, 350)
        w = random.uniform(1.0, 3.0)
        h = random.uniform(30, 90)
        color = random.choice([(70,75,80), (80,85,90), (60,65,70)])
        buildings.append((angle, w, h, color))
    # Foreground layer
    for _ in range(50):
        angle = random.uniform(190, 350)
        w = random.uniform(1.5, 4.0)
        h = random.uniform(50, 150)
        color = random.choice([(40,40,40), (30,35,40), (20,25,30), (50,50,60)])
        buildings.append((angle, w, h, color))
    # Iconic buildings
    buildings.append((270, 4.5, 260, (15, 15, 15), "SEARS"))
    buildings.append((300, 3.5, 230, (25, 25, 25), "HANCOCK"))
    buildings.append((285, 3.5, 210, (220, 220, 220), "AON"))
    return buildings

SKYLINE = generate_skyline()

def get_elevation(x, y, fairway_nodes, green_z):
    if not fairway_nodes: return 0.0
    if y <= fairway_nodes[0][0]: return fairway_nodes[0][3]
    if y >= fairway_nodes[-1][0]: return green_z
    for i in range(len(fairway_nodes)-1):
        if fairway_nodes[i][0] <= y <= fairway_nodes[i+1][0]:
            t = (y - fairway_nodes[i][0]) / (fairway_nodes[i+1][0] - fairway_nodes[i][0])
            return fairway_nodes[i][3] + t * (fairway_nodes[i+1][3] - fairway_nodes[i][3])
    return 0.0

def generate_course():
    course = []
    # Generate 18 holes
    pars = [4, 4, 3, 4, 5, 4, 4, 3, 4, 5, 4, 4, 3, 5, 4, 4, 3, 5]
    for i, p in enumerate(pars):
        if p == 3: dist = random.randint(140, 200)
        elif p == 4: dist = random.randint(350, 450)
        else: dist = random.randint(500, 600)
        curve_dir = 12 if i % 2 == 0 else -12
        
        gw1, gh1 = random.uniform(10, 16), random.uniform(12, 18)
        gw2, gh2 = random.uniform(12, 18), random.uniform(10, 16)
        ox, oy = random.uniform(-6, 6), random.uniform(-6, 6)
        
        hole_x = math.sin(dist*0.01)*curve_dir
        
        fairway = []
        for y in range(-20, dist+41, 20):
            z = math.sin(y * 0.02 + i) * 6.0 if p != 3 else 0.0
            x = math.sin(y*0.01)*curve_dir
            fairway.append((y, x, random.uniform(25, 35), z))
            
        green_z = fairway[-1][3]
        
        bunkers = []
        # Bunkers guarding the green
        bunkers.append((hole_x + random.choice([-15, 15]), dist + random.choice([-10, 10]), random.uniform(5, 9), green_z))
        if p > 3:
            fy = dist * random.uniform(0.5, 0.8)
            fx = math.sin(fy*0.01)*curve_dir + random.choice([-20, 20])
            fz = math.sin(fy * 0.02 + i) * 6.0
            bunkers.append((fx, fy, random.uniform(6, 12), fz))
            
        trees = []
        for _ in range(10 + p*6):
            ty = random.uniform(20, dist + 20)
            tx = math.sin(ty*0.01)*curve_dir + random.choice([random.uniform(-60, -30), random.uniform(30, 60)])
            tz = math.sin(ty * 0.02 + i) * 6.0
            trees.append((tx, ty, tz, random.uniform(20, 50), random.uniform(4, 9)))
            
        course.append({
            "par": p, "hole_pos": (math.sin(dist*0.01)*curve_dir, dist), 
            "fairway": fairway,
            "green": ((gw1, gh1), (gw2, gh2), (ox, oy)),
            "slope_waves": [
                (random.uniform(0.005, 0.010), random.uniform(0.04, 0.1), random.uniform(0.04, 0.1), random.uniform(0, 6.28), random.uniform(0, 6.28)),
                (random.uniform(0.002, 0.006), random.uniform(0.1, 0.2), random.uniform(0.1, 0.2), random.uniform(0, 6.28), random.uniform(0, 6.28))
            ],
            "green_z": green_z,
            "bunkers": bunkers,
            "trees": trees
        })
    return course

COURSE = generate_course()

def get_slope(x, y, waves, hole_pos):
    sx, sy = 0.0, 0.0
    for amp, fx, fy, px, py in waves:
        sx += math.cos(x * fx + px) * amp
        sy += math.sin(y * fy + py) * amp
        
    # Flatten the green near the hole
    dist = math.hypot(x - hole_pos[0], y - hole_pos[1])
    attenuation = min(1.0, dist / 4.0)
    return sx * attenuation, sy * attenuation

def is_on_green(bx, by, hole_pos, green_shape):
    g1_w, g1_h = green_shape[0]
    g2_w, g2_h = green_shape[1]
    ox, oy = green_shape[2]
    
    dx1, dy1 = bx - hole_pos[0], by - hole_pos[1]
    if (dx1**2 / g1_w**2) + (dy1**2 / g1_h**2) <= 1: return True
    
    dx2, dy2 = bx - (hole_pos[0] + ox), by - (hole_pos[1] + oy)
    if (dx2**2 / g2_w**2) + (dy2**2 / g2_h**2) <= 1: return True
    return False

def is_in_chipping_range(bx, by, hole_pos, green_shape, buffer_yards=4):
    g1_w, g1_h = green_shape[0]
    g2_w, g2_h = green_shape[1]
    ox, oy = green_shape[2]
    
    dx1, dy1 = bx - hole_pos[0], by - hole_pos[1]
    if (dx1**2 / (g1_w + buffer_yards)**2) + (dy1**2 / (g1_h + buffer_yards)**2) <= 1: return True
    
    dx2, dy2 = bx - (hole_pos[0] + ox), by - (hole_pos[1] + oy)
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

    def start_flight(self, dist, height, angle, wx, wy, power_mult, loft_offset, club_idx, face_angle):
        self.prev_x, self.prev_y = self.x, self.y
        self.is_moving = True
        self.flight_progress = 0
        self.bounce_count = 0
        self.loft_offset = loft_offset
        
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

        # Use purely the lateral wind for crosswind drift over time
        self.wind_x, self.wind_y = lat_wx / 60.0, lat_wy / 60.0
        self.strokes += 1

    def start_bounce(self):
        self.bounce_count += 1
        self.flight_progress = 0
        
        # High RPM reduces forward bounce or causes backspin
        # Adjusted to be more realistic (max ~4% backspin instead of 15%)
        spin_effect = (self.rpm - 2500) / 30000.0
        dist_damp = 0.15 - spin_effect
        dist_damp = max(-0.04, min(0.25, dist_damp))
        
        height_damp = 0.2 + (self.loft_offset / 120.0)
        height_damp = max(0.1, min(0.3, height_damp))
        
        self.dist *= dist_damp
        self.height *= height_damp
        old_flight_duration = self.flight_duration
        self.flight_duration = max(5, int(self.flight_duration * 0.6))
        self.rpm = int(self.rpm * 0.5) # Spin decays after hitting the ground
        
        if self.flight_duration <= 5 or self.height < 0.5:
            self.is_moving = False
            self.z = 0
        else:
            # Maintain the current trajectory vector instead of resetting to aim angle
            self.angle = math.degrees(math.atan2(self.vx, self.vy))
            self.vx = self.vx * dist_damp * (old_flight_duration / self.flight_duration)
            self.vy = self.vy * dist_damp * (old_flight_duration / self.flight_duration)
            self.max_height = self.height
            self.wind_x *= 0.5
            self.wind_y *= 0.5
            self.curve_accel_x *= 0.3
            self.curve_accel_y *= 0.3

    def update(self):
        if self.is_moving:
            self.flight_progress += 1
            t = self.flight_progress / self.flight_duration
            self.z = 4 * self.max_height * t * (1 - t)
            
            self.vx += self.curve_accel_x
            self.vy += self.curve_accel_y
            
            # Wind affects the ball more at higher altitudes
            altitude_wind_mult = self.z / 40.0
            self.x += self.vx + (self.wind_x * altitude_wind_mult)
            self.y += self.vy + (self.wind_y * altitude_wind_mult)
            
            if self.flight_progress >= self.flight_duration:
                self.z = 0
                self.start_bounce()

def project(obj_x, obj_y, obj_z, cam_x, cam_y, cam_angle, w, h):
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
    sy = horizon + (h - horizon) * (15 / (ry + 15)) - (obj_z * factor)
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
    options = [
        {"text": "1. Beginner (No Wind)", "diff": 0, "rect": pygame.Rect(0, 0, 0, 0)},
        {"text": "2. Amateur (Light Wind)", "diff": 15, "rect": pygame.Rect(0, 0, 0, 0)},
        {"text": "3. Pro (Heavy Wind)", "diff": 30, "rect": pygame.Rect(0, 0, 0, 0)}
    ]

    while difficulty is None:
        curr_w, curr_h = screen.get_size()
        screen.fill((30, 30, 30))
        
        title = font_large.render("MEIGS FIELD GOLF COURSE", True, WHITE)
        screen.blit(title, (curr_w//2 - title.get_width()//2, 120))
        
        mouse_pos = pygame.mouse.get_pos()
        
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
                if name_rect.collidepoint(e.pos):
                    input_active = True
                else:
                    input_active = False
                    for opt in options:
                        if opt["rect"].collidepoint(e.pos):
                            difficulty = opt["diff"]
                        
    network = P2PNetwork(player_id=player_name)

    hole_idx = 0
    scores = [None] * 18
    hole_data = COURSE[hole_idx]
    hole_pos = hole_data["hole_pos"]
    fairway_nodes = hole_data["fairway"]
    par = hole_data["par"]
    green_shape = hole_data["green"]
    slope_waves = hole_data["slope_waves"]
    green_z = hole_data["green_z"]

    ball = Ball()
    wind_rng = random.Random(312 + hole_idx)
    wx, wy = wind_rng.uniform(-difficulty, difficulty), wind_rng.uniform(-difficulty, difficulty)
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
                
                if not handled_menu:
                    if pygame.Rect(0, 0, 60, 24).collidepoint(event.pos): active_menu = "File"; handled_menu = True
                    elif pygame.Rect(60, 0, 100, 24).collidepoint(event.pos): active_menu = "Options"; handled_menu = True
                    else: active_menu = None
                else:
                    active_menu = None
                    
                if handled_menu: continue

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE: running = False
                if event.key == pygame.K_c: show_scorecard = not show_scorecard
                
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
                    ball.start_flight(dist, height, aim_angle, wx, wy, effective_power, trajectory_offset, club_idx, face_angle)
                    is_swinging = False; power = 0.0

            # Putting Event Handling
            if state == "GREEN" and ball.putt_vx == 0 and ball.putt_vy == 0 and ball.putt_z == 0:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    ball.ds = mouse_pos
                    ball.is_dragging = True
                if event.type == pygame.MOUSEBUTTONUP and ball.is_dragging:
                    ball.prev_x = hole_pos[0] + (ball.putt_x - curr_w//2) / 28.0
                    ball.prev_y = hole_pos[1] - (ball.putt_y - curr_h//2) / 28.0
                    power_mult = ball.lie / 100.0
                    if ball.chipping:
                        club_pwr = CLUBS[club_idx][1] / 125.0
                        club_lft = CLUBS[club_idx][3] / 46.0
                        ball.putt_vx = (ball.ds[0] - mouse_pos[0]) * 0.15 * power_mult * club_pwr
                        ball.putt_vy = (ball.ds[1] - mouse_pos[1]) * 0.15 * power_mult * club_pwr
                        drag_dist = math.hypot(ball.ds[0] - mouse_pos[0], ball.ds[1] - mouse_pos[1])
                        ball.putt_vz = drag_dist * 0.15 * club_lft
                    else:
                        ball.putt_vx = (ball.ds[0] - mouse_pos[0]) * 0.12 * power_mult
                        ball.putt_vy = (ball.ds[1] - mouse_pos[1]) * 0.12 * power_mult
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
                        if hole_idx >= len(COURSE):
                            main() # Restart game if 18 holes are finished
                            return
                        hole_data = COURSE[hole_idx]
                        hole_pos = hole_data["hole_pos"]
                        fairway_nodes = hole_data["fairway"]
                        par = hole_data["par"]
                        green_shape = hole_data["green"]
                        slope_waves = hole_data["slope_waves"]
                        green_z = hole_data["green_z"]
                        ball = Ball()
                        wind_rng = random.Random(312 + hole_idx)
                        wx, wy = wind_rng.uniform(-difficulty, difficulty), wind_rng.uniform(-difficulty, difficulty)
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
            if keys[pygame.K_a]: face_angle -= 0.5
            if keys[pygame.K_d]: face_angle += 0.5
            
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
        if state == "3D":
            was_moving = ball.is_moving
            ball.update()
            
            cam_angle += (aim_angle - cam_angle) * 0.1
            target_cam_x = ball.x - math.sin(math.radians(cam_angle)) * 18
            target_cam_y = ball.y - math.cos(math.radians(cam_angle)) * 18
            cam_x += (target_cam_x - cam_x) * 0.1
            cam_y += (target_cam_y - cam_y) * 0.1
            
            if was_moving and not ball.is_moving:
                # Find nearest fairway node to determine boundaries dynamically
                closest_x = 0
                closest_w = 30
                min_dist = 9999
                for y, x, w, _ in fairway_nodes:
                    if abs(y - ball.y) < min_dist:
                        min_dist = abs(y - ball.y)
                        closest_x = x
                        closest_w = w
                        
                if abs(ball.x - closest_x) > 120 or ball.y < -50 or ball.y > hole_pos[1] + 150:
                    ball.strokes += 2
                    ball.x, ball.y = ball.prev_x, ball.prev_y
                    msg_text = "OUT OF BOUNDS! +2 STROKES"
                    msg_timer = 180
                elif is_in_chipping_range(ball.x, ball.y, hole_pos, green_shape, buffer_yards=4):
                    state = "GREEN"
                    ball.putt_x = curr_w // 2 + (ball.x - hole_pos[0]) * 28.0
                    ball.putt_y = curr_h // 2 + (hole_pos[1] - ball.y) * 28.0
                    if is_on_green(ball.x, ball.y, hole_pos, green_shape):
                        ball.lie = 100
                        ball.chipping = False
                    else:
                        ball.lie = random.randint(20, 90)
                        ball.chipping = True if ball.lie < 70 else False
                else:
                    if abs(ball.x - closest_x) <= closest_w:
                        ball.lie = 100
                    else:
                        ball.lie = random.randint(20, 100)

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
                    roll_factor = max(0.1, 0.4 + (1.0 - (CLUBS[club_idx][3] / 46.0)) * 0.6) if ball.chipping else 0.4
                    ball.putt_vx *= roll_factor
                    ball.putt_vy *= roll_factor
            else:
                ball.putt_x += ball.putt_vx; ball.putt_y += ball.putt_vy
                
                sim_x = hole_pos[0] + (ball.putt_x - curr_w//2) / 28.0
                sim_y = hole_pos[1] - (ball.putt_y - curr_h//2) / 28.0
                
                if is_on_green(sim_x, sim_y, hole_pos, green_shape):
                    sx, sy = get_slope(sim_x, sim_y, slope_waves, hole_pos)
                    ball.putt_vx += sx * 2.8
                    ball.putt_vy += sy * 2.8
                    ball.putt_vx *= 0.97
                    ball.putt_vy *= 0.97
                    if math.hypot(ball.putt_vx, ball.putt_vy) < 0.7 and math.hypot(sx, sy) < 0.02:
                        ball.putt_vx *= 0.5  # Strong static friction to prevent endless rolling
                        ball.putt_vy *= 0.5
                else:
                    ball.putt_vx *= 0.7 # Fringe/Rough friction
                    ball.putt_vy *= 0.7
            
            is_moving_2d = abs(ball.putt_vx) >= 0.06 or abs(ball.putt_vy) >= 0.06 or ball.putt_z > 0
            
            if ball.putt_x < 0 or ball.putt_x > curr_w or ball.putt_y < 0 or ball.putt_y > curr_h:
                while abs(ball.putt_vx) >= 0.06 or abs(ball.putt_vy) >= 0.06 or ball.putt_z > 0:
                    if ball.putt_z > 0 or ball.putt_vz != 0:
                        ball.putt_x += ball.putt_vx
                        ball.putt_y += ball.putt_vy
                        ball.putt_z += ball.putt_vz
                        ball.putt_vz -= 2.3
                        if ball.putt_z <= 0:
                            ball.putt_z = 0; ball.putt_vz = 0
                            roll_factor = max(0.1, 0.4 + (1.0 - (CLUBS[club_idx][3] / 46.0)) * 0.6) if ball.chipping else 0.4
                            ball.putt_vx *= roll_factor; ball.putt_vy *= roll_factor
                    else:
                        ball.putt_x += ball.putt_vx; ball.putt_y += ball.putt_vy
                        sim_x = hole_pos[0] + (ball.putt_x - curr_w//2) / 28.0
                        sim_y = hole_pos[1] - (ball.putt_y - curr_h//2) / 28.0
                        if is_on_green(sim_x, sim_y, hole_pos, green_shape):
                            sx, sy = get_slope(sim_x, sim_y, slope_waves, hole_pos)
                            ball.putt_vx += sx * 2.8; ball.putt_vy += sy * 2.8
                            ball.putt_vx *= 0.97; ball.putt_vy *= 0.97
                            if math.hypot(ball.putt_vx, ball.putt_vy) < 0.7 and math.hypot(sx, sy) < 0.02:
                                ball.putt_vx *= 0.5; ball.putt_vy *= 0.5
                        else:
                            ball.putt_vx *= 0.7; ball.putt_vy *= 0.7
                state = "3D"
                ball.is_moving = False
                ball.x = hole_pos[0] + (ball.putt_x - curr_w//2) / 28.0
                ball.y = hole_pos[1] - (ball.putt_y - curr_h//2) / 28.0
                ball.z = 0
                ball.putt_vx = ball.putt_vy = ball.putt_z = ball.putt_vz = 0
                closest_x = 0; closest_w = 30; min_dist = 9999
                for y, x, w, _ in fairway_nodes:
                    if abs(y - ball.y) < min_dist:
                        min_dist = abs(y - ball.y)
                        closest_x = x; closest_w = w
                if abs(ball.x - closest_x) > 120 or ball.y < -50 or ball.y > hole_pos[1] + 150:
                    ball.x, ball.y = ball.prev_x, ball.prev_y
                    msg_text = "OUT OF BOUNDS! +2 STROKES"
                    msg_timer = 180
                    ball.strokes += 2
                else:
                    ball.lie = 100 if abs(ball.x - closest_x) <= closest_w else random.randint(20, 100)
                ball.chipping = False
                aim_angle = math.degrees(math.atan2(hole_pos[0] - ball.x, hole_pos[1] - ball.y))
                cam_angle = aim_angle
                is_moving_2d = False
                was_moving_2d = False

            if not is_moving_2d and was_moving_2d:
                ball.putt_vx = ball.putt_vy = ball.putt_z = 0
                sim_x = hole_pos[0] + (ball.putt_x - curr_w//2) / 28.0
                sim_y = hole_pos[1] - (ball.putt_y - curr_h//2) / 28.0
                if is_on_green(sim_x, sim_y, hole_pos, green_shape):
                    ball.lie = 100
                    ball.chipping = False
                else:
                    ball.lie = random.randint(20, 90)
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
            pygame.draw.rect(screen, ROUGH, (0, int(curr_h*0.38), curr_w, curr_h))

            # --- Panorama (Skyline & Lake) ---
            horizon = int(curr_h * 0.38)
            fov = 75.0 # View angle width in degrees
            deg_to_px = curr_w / fov
            pano_w = int(360 * deg_to_px)
            ca = cam_angle % 360
            offset_x = - (ca * deg_to_px) + (curr_w / 2)

            # Draw Lake Michigan (from 0 to 180 degrees)
            lake_h = max(5, int(curr_h * 0.015))
            for shift in [0, pano_w, -pano_w]:
                rx = offset_x + shift
                lx = int(rx)
                lw = int(180 * deg_to_px)
                if lx + lw > 0 and lx < curr_w:
                    pygame.draw.rect(screen, (40, 100, 160), (lx, horizon - lake_h, lw, lake_h))
                    pygame.draw.line(screen, (194, 178, 128), (lx, horizon), (lx + lw, horizon), 2)
            
            # Draw Skyline (angles 190 to 350)
            for b in SKYLINE:
                x1 = b[0] * deg_to_px
                w_px = max(2, int(b[1] * deg_to_px))
                h_px = int(b[2] * (curr_h / 720.0)) # scale height relative to base window size
                
                for shift in [0, pano_w, -pano_w]:
                    rx = offset_x + x1 + shift
                    if rx + w_px > 0 and rx < curr_w:
                        pygame.draw.rect(screen, b[3], (int(rx), horizon - h_px, w_px, h_px))
                        if len(b) > 4:
                            if b[4] == "SEARS":
                                pygame.draw.line(screen, (0,0,0), (int(rx + w_px*0.25), horizon - h_px), (int(rx + w_px*0.25), horizon - h_px - 35), 2)
                                pygame.draw.line(screen, (0,0,0), (int(rx + w_px*0.75), horizon - h_px), (int(rx + w_px*0.75), horizon - h_px - 35), 2)
                            elif b[4] == "HANCOCK":
                                pygame.draw.line(screen, (0,0,0), (int(rx + w_px*0.35), horizon - h_px), (int(rx + w_px*0.35), horizon - h_px - 25), 2)
                                pygame.draw.line(screen, (0,0,0), (int(rx + w_px*0.65), horizon - h_px), (int(rx + w_px*0.65), horizon - h_px - 25), 2)
                                pygame.draw.line(screen, (10,10,10), (int(rx), horizon - h_px), (int(rx + w_px), horizon - h_px + 40), 1)
                                pygame.draw.line(screen, (10,10,10), (int(rx + w_px), horizon - h_px), (int(rx), horizon - h_px + 40), 1)

            # --- OB Stakes (White Posts) ---
            for i, node in enumerate(fairway_nodes):
                if i % 2 == 0:  # Every 40 yards
                    y, x, w, _ = node
                    for sx in [x - 120, x + 120]:
                        base = project(sx, y, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                        if base and base[3] > -14:
                            top = project(sx, y, 1.5, cam_x, cam_y, cam_angle, curr_w, curr_h)
                            if top:
                                pygame.draw.line(screen, WHITE, base[:2], top[:2], max(1, int(2.5*base[2])))
            
            # OB Stakes behind Green
            for sx in range(int(hole_pos[0]) - 80, int(hole_pos[0]) + 81, 20):
                base = project(sx, hole_pos[1] + 150, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if base and base[3] > -14:
                    top = project(sx, hole_pos[1] + 150, 1.5, cam_x, cam_y, cam_angle, curr_w, curr_h)
                    if top:
                        pygame.draw.line(screen, WHITE, base[:2], top[:2], max(1, int(2.5*base[2])))
                        
            # OB Stakes behind Tee
            for sx in range(-80, 81, 20):
                base = project(sx, -50, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if base and base[3] > -14:
                    top = project(sx, -50, 1.5, cam_x, cam_y, cam_angle, curr_w, curr_h)
                    if top:
                        pygame.draw.line(screen, WHITE, base[:2], top[:2], max(1, int(2.5*base[2])))

            for i in range(len(fairway_nodes)-1):
                y1, x1, w1, _ = fairway_nodes[i]; y2, x2, w2, _ = fairway_nodes[i+1]
                p1l = project(x1-w1, y1, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                p1r = project(x1+w1, y1, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                p2l = project(x2-w2, y2, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                p2r = project(x2+w2, y2, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if p1l and p1r and p2l and p2r:
                    if p1l[3] > -14 or p2l[3] > -14 or p1r[3] > -14 or p2r[3] > -14:
                        pygame.draw.polygon(screen, FAIRWAY, [p1l[:2], p1r[:2], p2r[:2], p2l[:2]])

            # --- Tee Box ---
            tb_p1l = project(-12, -10, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
            tb_p1r = project(12, -10, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
            tb_p2l = project(-12, 8, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
            tb_p2r = project(12, 8, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
            if tb_p1l and tb_p1r and tb_p2l and tb_p2r:
                if tb_p1l[3] > -14 or tb_p2l[3] > -14 or tb_p1r[3] > -14 or tb_p2r[3] > -14:
                    pygame.draw.polygon(screen, GREEN_COLOR, [tb_p1l[:2], tb_p1r[:2], tb_p2r[:2], tb_p2l[:2]])
                    pygame.draw.polygon(screen, WHITE, [tb_p1l[:2], tb_p1r[:2], tb_p2r[:2], tb_p2l[:2]], 1)
                
            tm1 = project(-4, 0, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
            tm2 = project(4, 0, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
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
                gp1 = project(hole_pos[0] + math.cos(rad)*g1_w, hole_pos[1] + math.sin(rad)*g1_h, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if gp1: green1_pts.append(gp1)
                gp2 = project(hole_pos[0] + ox + math.cos(rad)*g2_w, hole_pos[1] + oy + math.sin(rad)*g2_h, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if gp2: green2_pts.append(gp2)
            if len(green1_pts) > 2 and any(pt[3] > -14 for pt in green1_pts): pygame.draw.polygon(screen, GREEN_COLOR, [pt[:2] for pt in green1_pts])
            if len(green2_pts) > 2 and any(pt[3] > -14 for pt in green2_pts): pygame.draw.polygon(screen, GREEN_COLOR, [pt[:2] for pt in green2_pts])

            f = project(hole_pos[0], hole_pos[1], 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
            if f and f[3] > -14:
                pygame.draw.line(screen, WHITE, (f[0], f[1]), (f[0], f[1]-max(1, int(12*f[2]))), 2)
                pygame.draw.rect(screen, RED, (f[0], f[1]-max(1, int(12*f[2])), max(1, int(4*f[2])), max(1, int(3*f[2]))))
            
            # --- Draw Player ---
            if not ball.is_moving:
                p_angle = math.radians(aim_angle - 90)
                px = ball.x + 2.5 * math.sin(p_angle)
                py = ball.y + 2.5 * math.cos(p_angle)
                
                feet_l = project(px - 1.0*math.cos(p_angle), py + 1.0*math.sin(p_angle), 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                feet_r = project(px + 1.0*math.cos(p_angle), py - 1.0*math.sin(p_angle), 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                waist = project(px, py, 2.5, cam_x, cam_y, cam_angle, curr_w, curr_h)
                neck = project(px, py, 4.5, cam_x, cam_y, cam_angle, curr_w, curr_h)
                head = project(px, py, 5.5, cam_x, cam_y, cam_angle, curr_w, curr_h)
                
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
                        club_z = 6 * power
                        hands_x = px + 1.5 * math.sin(swing_rot)
                        hands_y = py + 1.5 * math.cos(swing_rot)
                        hands_z = 2.5 + 2 * power
                    else:
                        club_x, club_y, club_z = ball.x, ball.y, 0
                        aim_rad = math.radians(aim_angle)
                        hands_x = px + 1.5 * math.sin(aim_rad)
                        hands_y = py + 1.5 * math.cos(aim_rad)
                        hands_z = 2.0

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
                    p_b = project(p_state['x'], p_state['y'], p_state['z'], cam_x, cam_y, cam_angle, curr_w, curr_h)
                    if p_b and p_b[3] > -14:
                        pygame.draw.circle(screen, (255, 100, 100), (p_b[0], p_b[1]), max(1, int(0.15*p_b[2])))
                        screen.blit(font_small.render(p_id, True, (255, 150, 150)), (p_b[0] + 10, p_b[1] - 10))

            b = project(ball.x, ball.y, ball.z, cam_x, cam_y, cam_angle, curr_w, curr_h)
            if b and b[3] > -14: pygame.draw.circle(screen, WHITE, (b[0], b[1]), max(1, int(0.15*b[2])))

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
                
                for step in range(101):
                    t = step / 100.0
                    pz = ball.z + 4 * adj_height * t * (1 - t)
                    
                    sim_vx += sim_cdx * sim_caccel
                    sim_vy += sim_cdy * sim_caccel
                    
                    alt_wind_mult = pz / 40.0
                    sim_x += sim_vx + (sim_wx * alt_wind_mult)
                    sim_y += sim_vy + (sim_wy * alt_wind_mult)
                    
                    if step % 6 == 0 or step == 100:
                        proj_pt = project(sim_x, sim_y, pz, cam_x, cam_y, cam_angle, curr_w, curr_h)
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
            screen.fill(ROUGH)
            g1_w, g1_h = green_shape[0]
            g2_w, g2_h = green_shape[1]
            ox, oy = green_shape[2]
            pygame.draw.ellipse(screen, GREEN_COLOR, pygame.Rect(curr_w//2 - int(g1_w*28), curr_h//2 - int(g1_h*28), int(g1_w*56), int(g1_h*56)))
            pygame.draw.ellipse(screen, GREEN_COLOR, pygame.Rect(curr_w//2 + int(ox*28) - int(g2_w*28), curr_h//2 - int(oy*28) - int(g2_h*28), int(g2_w*56), int(g2_h*56)))
            
            # Draw slope grid
            for gy in range(curr_h//2 - 900, curr_h//2 + 900, 70):
                for gx in range(curr_w//2 - 900, curr_w//2 + 900, 70):
                    sim_x = hole_pos[0] + (gx - curr_w//2) / 28.0
                    sim_y = hole_pos[1] - (gy - curr_h//2) / 28.0
                    if is_on_green(sim_x, sim_y, hole_pos, green_shape):
                        sx, sy = get_slope(sim_x, sim_y, slope_waves, hole_pos)
                        draw_sx = sx * 4500
                        draw_sy = sy * 4500
                        if abs(draw_sx) > 1 or abs(draw_sy) > 1:
                            pygame.draw.line(screen, (35, 140, 35), (gx, gy), (gx + draw_sx, gy + draw_sy), 2)
                            pygame.draw.circle(screen, (200, 255, 200), (int(gx + draw_sx), int(gy + draw_sy)), 2)

            hole_screen_pos = (curr_w//2, curr_h//2)
            pygame.draw.circle(screen, HOLE_COLOR, hole_screen_pos, 16)
            
            # --- FIXED: Putter Line ---
            if ball.is_dragging:
                # Line from ball to mouse (Slingshot)
                pygame.draw.line(screen, WHITE, (int(ball.putt_x), int(ball.putt_y - ball.putt_z)), mouse_pos, 2)

            if ball.putt_z > 0:
                pygame.draw.circle(screen, (0, 0, 0), (int(ball.putt_x), int(ball.putt_y)), 7) # shadow
            pygame.draw.circle(screen, WHITE, (int(ball.putt_x), int(ball.putt_y - ball.putt_z)), 7)
            
            # --- Draw Peers in 2D ---
            for p_id, p_state in active_peers:
                if p_state['hole'] == hole_idx and p_state['state'] == "GREEN":
                    px, py, pz = int(p_state['putt_x']), int(p_state['putt_y']), p_state['putt_z']
                    if pz > 0: pygame.draw.circle(screen, (0, 0, 0), (px, py), 7)
                    pygame.draw.circle(screen, (255, 100, 100), (px, int(py - pz)), 7)
                    screen.blit(font_small.render(p_id, True, (255, 150, 150)), (px + 10, py - 20))
            
            mode_str = f"CHIP ({CLUBS[club_idx][0]})" if ball.chipping else "PUTT"
            lie_str = f"Lie: {ball.lie}%"
            color = WHITE if ball.lie >= 90 else YELLOW
            txt = f"{mode_str} - {lie_str} - Drag BACK to aim. SPACE to toggle. W/S to change club."
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
                        
            draw_scorecard(screen, curr_w, curr_h, group_scores, COURSE, current_tee_order)

        pygame.display.flip()
        clock.tick(60)
    pygame.quit()

if __name__ == "__main__":
    main()