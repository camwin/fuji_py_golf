import pygame
import math
import random

# --- Window Setup ---
WIDTH, HEIGHT = 1280, 720 
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption("Fuji Golf Successor")

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
    ["Driver", 265, 25], ["3 Wood", 240, 30], ["5 Wood", 220, 35],
    ["3 Iron", 205, 40], ["4 Iron", 195, 45], ["5 Iron", 185, 50],
    ["6 Iron", 175, 55], ["7 Iron", 165, 60], ["8 Iron", 155, 65],
    ["9 Iron", 145, 70], ["PW", 125, 80], ["GW", 110, 90],
    ["SW", 95, 100], ["LW", 75, 110]
]

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
        self.ds = None # Drag start
        self.is_dragging = False

    def start_flight(self, dist, height, angle, wx, wy, power_mult, loft_offset, club_idx):
        self.prev_x, self.prev_y = self.x, self.y
        self.is_moving = True
        self.flight_progress = 0
        self.bounce_count = 0
        self.loft_offset = loft_offset
        self.rpm = max(500, int((2000 + (club_idx * 300) + (loft_offset * 150)) * power_mult))
        
        rad = math.radians(angle)
        actual_dist = (dist * power_mult) * random.uniform(0.98, 1.02)
        
        self.dist = actual_dist
        self.height = height * power_mult
        self.angle = angle
        self.flight_duration = 100
        
        self.vy = (self.dist / self.flight_duration) * math.cos(rad)
        self.vx = (self.dist / self.flight_duration) * math.sin(rad)
        self.max_height = self.height
        self.wind_x, self.wind_y = wx / 70.0, wy / 70.0
        self.strokes += 1

    def start_bounce(self):
        self.bounce_count += 1
        self.flight_progress = 0
        
        # High RPM reduces forward bounce or causes backspin!
        dist_damp = 0.5 - ((self.rpm - 2000) / 8500.0) 
        dist_damp = max(-0.3, min(0.6, dist_damp))
        
        height_damp = 0.25 + (self.loft_offset / 100.0)
        height_damp = max(0.1, min(0.4, height_damp))
        
        self.dist *= dist_damp
        self.height *= height_damp
        self.flight_duration = max(5, int(self.flight_duration * 0.6))
        self.rpm = int(self.rpm * 0.5) # Spin decays after hitting the ground
        
        if self.flight_duration <= 5 or self.height < 0.5:
            self.is_moving = False
            self.z = 0
        else:
            rad = math.radians(self.angle)
            self.vy = (self.dist / self.flight_duration) * math.cos(rad)
            self.vx = (self.dist / self.flight_duration) * math.sin(rad)
            self.max_height = self.height
            self.wind_x *= 0.5
            self.wind_y *= 0.5

    def update(self):
        if self.is_moving:
            self.flight_progress += 1
            t = self.flight_progress / self.flight_duration
            self.z = 4 * self.max_height * t * (1 - t)
            
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
    
    if ry < -10: 
        ry = -10  # Clamp to a near plane so ground polys stretch off the bottom of the screen!
    factor = (h * 0.5) / (ry + 15)
    sx = (w // 2) + (rx * factor)
    horizon = h * 0.38
    sy = horizon + (h - horizon) * (15 / (ry + 15)) - (obj_z * factor)
    return int(sx), int(sy), factor

def draw_hud(screen, curr_w, curr_h, ball, hole_pos, club_idx, power, wx, wy, is_swinging, trajectory_offset, cam_angle, show_wind_preview):
    # --- Club Inventory (Left Side) ---
    pygame.draw.rect(screen, (0,0,0,100), (10, 10, 180, 330))
    for i, c in enumerate(CLUBS):
        color = YELLOW if i == club_idx else WHITE
        txt = font_small.render(f"{c[0]}: {c[1]}y", True, color)
        screen.blit(txt, (20, 20 + i * 22))

    # --- Wind & Distance (Right Side) ---
    dist = int(math.hypot(ball.x-hole_pos[0], ball.y-hole_pos[1]))
    screen.blit(font_med.render(f"{dist} YDS TO PIN", True, WHITE), (curr_w - 280, 20))
    screen.blit(font_med.render(f"STROKES: {ball.strokes}", True, WHITE), (curr_w - 280, 60))
    screen.blit(font_med.render(f"LIE: {ball.lie}%", True, WHITE if ball.lie >= 90 else YELLOW), (curr_w - 280, 100))
    loft_str = f"+{int(trajectory_offset)}" if trajectory_offset > 0 else str(int(trajectory_offset))
    screen.blit(font_med.render(f"LOFT: {loft_str}°", True, WHITE), (curr_w - 280, 140))
    
    display_rpm = ball.rpm if ball.is_moving else max(500, int(2000 + (club_idx * 300) + (trajectory_offset * 150)))
    screen.blit(font_med.render(f"SPIN: {display_rpm} RPM", True, WHITE), (curr_w - 280, 180))
    
    # Wind Compass
    cx, cy = curr_w - 80, 150
    pygame.draw.circle(screen, WHITE, (cx, cy), 40, 2)
    mag = math.hypot(wx, wy)
    if mag > 0:
        rad = math.radians(cam_angle)
        local_wx = wx * math.cos(rad) - wy * math.sin(rad)
        local_wy = wx * math.sin(rad) + wy * math.cos(rad)
        ex, ey = cx + (local_wx/mag)*35, cy - (local_wy/mag)*35
        pygame.draw.line(screen, YELLOW, (cx, cy), (ex, ey), 3)
    screen.blit(font_small.render(f"WIND: {int(mag)} MPH", True, WHITE), (cx - 55, cy + 50))
    
    preview_color = YELLOW if show_wind_preview else GRAY
    screen.blit(font_small.render(f"WIND PREVIEW: {'ON' if show_wind_preview else 'OFF'} (P)", True, preview_color), (cx - 95, cy + 75))

    # --- Power Meter (Bottom Center) ---
    if is_swinging or power > 0:
        mw, mh = 300, 25
        mx, my = curr_w // 2 - mw // 2, curr_h - 100
        pygame.draw.rect(screen, GRAY, (mx, my, mw, mh))
        pygame.draw.rect(screen, YELLOW, (mx, my, int(mw * power), mh))
        pygame.draw.rect(screen, WHITE, (mx, my, mw, mh), 2)
        label = font_small.render(f"POWER: {int(power*100)}%", True, WHITE)
        screen.blit(label, (mx + 100, my - 25))

def main():
    difficulty = None
    options = [
        {"text": "1. Beginner (No Wind)", "diff": 0, "rect": pygame.Rect(0, 0, 0, 0)},
        {"text": "2. Amateur (Light Wind)", "diff": 8, "rect": pygame.Rect(0, 0, 0, 0)},
        {"text": "3. Pro (Heavy Wind)", "diff": 18, "rect": pygame.Rect(0, 0, 0, 0)}
    ]

    while difficulty is None:
        curr_w, curr_h = screen.get_size()
        screen.fill((30, 30, 30))
        
        title = font_large.render("FUJI GOLF SUCCESSOR", True, WHITE)
        screen.blit(title, (curr_w//2 - title.get_width()//2, 120))
        
        mouse_pos = pygame.mouse.get_pos()
        for i, opt in enumerate(options):
            rect = pygame.Rect(curr_w//2 - 200, 220 + i * 70, 400, 50)
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
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                for opt in options:
                    if opt["rect"].collidepoint(e.pos):
                        difficulty = opt["diff"]

    ball = Ball()
    wx, wy = random.uniform(-difficulty, difficulty), random.uniform(-difficulty, difficulty)
    cam_x, cam_y = 0, -20
    cam_angle = 0.0
    aim_angle = 0.0
    trajectory_offset = 0.0
    show_wind_preview = False
    club_idx = 0
    state = "3D"
    hole_pos = (0, 400)
    fairway_nodes = [(yrd, math.sin(yrd*0.02)*12, 35) for yrd in range(40, 401, 20)]
    
    is_swinging = False
    power = 0.0
    msg_text = ""
    msg_timer = 0

    running = True
    while running:
        curr_w, curr_h = screen.get_size()
        mouse_pos = pygame.mouse.get_pos()
        screen.fill(SKY)

        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE: running = False
                if event.key == pygame.K_r: main(); return
                
                if not ball.is_moving and state == "3D":
                    if event.key == pygame.K_w: club_idx = (club_idx - 1) % len(CLUBS)
                    if event.key == pygame.K_s: club_idx = (club_idx + 1) % len(CLUBS)
                    if event.key == pygame.K_p: show_wind_preview = not show_wind_preview
                    if event.key == pygame.K_SPACE:
                        is_swinging = True; power = 0.0

            if event.type == pygame.KEYUP:
                if event.key == pygame.K_SPACE and is_swinging:
                    effective_power = power * (ball.lie / 100.0)
                    dist = CLUBS[club_idx][1] - (trajectory_offset * 2.5)
                    height = CLUBS[club_idx][2] + (trajectory_offset * 1.5)
                    ball.start_flight(dist, height, aim_angle, wx, wy, effective_power, trajectory_offset, club_idx)
                    is_swinging = False; power = 0.0

            # Putting Event Handling
            if state == "GREEN" and ball.putt_vx == 0:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    ball.ds = mouse_pos
                    ball.is_dragging = True
                if event.type == pygame.MOUSEBUTTONUP and ball.is_dragging:
                    ball.putt_vx = (ball.ds[0] - mouse_pos[0]) * 0.12
                    ball.putt_vy = (ball.ds[1] - mouse_pos[1]) * 0.12
                    ball.strokes += 1
                    ball.is_dragging = False

        if is_swinging:
            power += 0.015
            if power > 1.0: power = 0.0 # Reset on over-swing

        keys = pygame.key.get_pressed()
        if not ball.is_moving and not is_swinging and state == "3D":
            if keys[pygame.K_LEFT]: aim_angle -= 0.8
            if keys[pygame.K_RIGHT]: aim_angle += 0.8
            if keys[pygame.K_UP]: trajectory_offset += 0.5
            if keys[pygame.K_DOWN]: trajectory_offset -= 0.5
            trajectory_offset = max(-15.0, min(15.0, trajectory_offset))

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
                rough_center_x = math.sin(ball.y * 0.02) * 12
                if abs(ball.x - rough_center_x) > 80 or ball.y < -50 or ball.y > 450:
                    ball.strokes += 2
                    ball.x, ball.y = ball.prev_x, ball.prev_y
                    msg_text = "OUT OF BOUNDS! +2 STROKES"
                    msg_timer = 180
                elif math.hypot(ball.x - hole_pos[0], ball.y - hole_pos[1]) < 25:
                    state = "GREEN"
                    ball.putt_x = curr_w // 2 + (ball.x - hole_pos[0]) * 20
                    ball.putt_y = curr_h // 2 + (hole_pos[1] - ball.y) * 20

        elif state == "GREEN":
            ball.putt_x += ball.putt_vx; ball.putt_y += ball.putt_vy
            ball.putt_vx *= 0.97; ball.putt_vy *= 0.97
            if abs(ball.putt_vx) < 0.05: ball.putt_vx = ball.putt_vy = 0
            if math.hypot(ball.putt_x - curr_w//2, ball.putt_y - curr_h//2) < 18 and math.hypot(ball.putt_vx, ball.putt_vy) < 3:
                state = "HOLE"

        # --- Rendering ---
        if state == "3D":
            pygame.draw.rect(screen, BROWN, (0, int(curr_h*0.38), curr_w, curr_h))
            
            rough_nodes = [(yrd, math.sin(yrd*0.02)*12, 80) for yrd in range(-100, 501, 20)]
            for i in range(len(rough_nodes)-1):
                y1, x1, w1 = rough_nodes[i]; y2, x2, w2 = rough_nodes[i+1]
                p1l = project(x1-w1, y1, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                p1r = project(x1+w1, y1, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                p2l = project(x2-w2, y2, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                p2r = project(x2+w2, y2, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if p1l and p2l: pygame.draw.polygon(screen, ROUGH, [p1l[:2], p1r[:2], p2r[:2], p2l[:2]])

            # --- Tee Box ---
            tb_p1l = project(-12, -10, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
            tb_p1r = project(12, -10, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
            tb_p2l = project(-12, 8, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
            tb_p2r = project(12, 8, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
            if tb_p1l and tb_p1r and tb_p2l and tb_p2r:
                pygame.draw.polygon(screen, GREEN_COLOR, [tb_p1l[:2], tb_p1r[:2], tb_p2r[:2], tb_p2l[:2]])
                pygame.draw.polygon(screen, WHITE, [tb_p1l[:2], tb_p1r[:2], tb_p2r[:2], tb_p2l[:2]], 1)
                tm1 = project(-4, 0, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                tm2 = project(4, 0, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if tm1: 
                    pygame.draw.circle(screen, RED, tm1[:2], max(2, int(4*tm1[2])))
                    pygame.draw.circle(screen, WHITE, tm1[:2], max(2, int(4*tm1[2])), 1)
                if tm2: 
                    pygame.draw.circle(screen, RED, tm2[:2], max(2, int(4*tm2[2])))
                    pygame.draw.circle(screen, WHITE, tm2[:2], max(2, int(4*tm2[2])), 1)

            for i in range(len(fairway_nodes)-1):
                y1, x1, w1 = fairway_nodes[i]; y2, x2, w2 = fairway_nodes[i+1]
                p1l = project(x1-w1, y1, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                p1r = project(x1+w1, y1, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                p2l = project(x2-w2, y2, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                p2r = project(x2+w2, y2, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if p1l and p2l: pygame.draw.polygon(screen, FAIRWAY, [p1l[:2], p1r[:2], p2r[:2], p2l[:2]])

            # Draw Green shape (matches 2D view)
            green1_pts = []
            green2_pts = []
            for a in range(0, 360, 10):
                rad = math.radians(a)
                gp1 = project(hole_pos[0] + math.cos(rad)*10, hole_pos[1] + math.sin(rad)*15, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if gp1: green1_pts.append(gp1[:2])
                gp2 = project(hole_pos[0] + math.cos(rad)*17.5, hole_pos[1] + math.sin(rad)*7.5, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if gp2: green2_pts.append(gp2[:2])
            if len(green1_pts) > 2: pygame.draw.polygon(screen, GREEN_COLOR, green1_pts)
            if len(green2_pts) > 2: pygame.draw.polygon(screen, GREEN_COLOR, green2_pts)

            f = project(hole_pos[0], hole_pos[1], 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
            if f:
                pygame.draw.line(screen, WHITE, (f[0], f[1]), (f[0], f[1]-int(90*f[2])), 2)
                pygame.draw.rect(screen, RED, (f[0], f[1]-int(90*f[2]), int(20*f[2]), int(15*f[2])))
            
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
                
                if head and waist and feet_l and feet_r and neck:
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
                        pygame.draw.circle(screen, (100, 100, 100), club_head[:2], max(2, int(1.5 * club_head[2])))

            b = project(ball.x, ball.y, ball.z, cam_x, cam_y, cam_angle, curr_w, curr_h)
            if b: pygame.draw.circle(screen, WHITE, (b[0], b[1]), max(1, int(0.15*b[2])))

            # --- Aim Indicator ---
            if not ball.is_moving:
                adj_dist = CLUBS[club_idx][1] - (trajectory_offset * 2.5)
                adj_height = CLUBS[club_idx][2] + (trajectory_offset * 1.5)
                base_target_x = ball.x + adj_dist * math.sin(math.radians(aim_angle))
                base_target_y = ball.y + adj_dist * math.cos(math.radians(aim_angle))
                
                arc_points = []
                sim_x, sim_y = ball.x, ball.y
                sim_vx = (base_target_x - ball.x) / 100.0
                sim_vy = (base_target_y - ball.y) / 100.0
                sim_wx = (wx / 70.0) if show_wind_preview else 0.0
                sim_wy = (wy / 70.0) if show_wind_preview else 0.0
                
                for step in range(101):
                    t = step / 100.0
                    pz = 4 * adj_height * t * (1 - t)
                    
                    alt_wind_mult = pz / 40.0
                    sim_x += sim_vx + (sim_wx * alt_wind_mult)
                    sim_y += sim_vy + (sim_wy * alt_wind_mult)
                    
                    if step % 6 == 0 or step == 100:
                        proj_pt = project(sim_x, sim_y, pz, cam_x, cam_y, cam_angle, curr_w, curr_h)
                        if proj_pt:
                            arc_points.append(proj_pt[:2])
                            
                t_proj = project(sim_x, sim_y, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                        
                if len(arc_points) > 1:
                    pygame.draw.lines(screen, YELLOW, False, arc_points, 1)

                if b and t_proj:
                    pygame.draw.circle(screen, YELLOW, (t_proj[0], t_proj[1]), max(2, int(15*t_proj[2])), 1)

            draw_hud(screen, curr_w, curr_h, ball, hole_pos, club_idx, power, wx, wy, is_swinging, trajectory_offset, cam_angle, show_wind_preview)

        elif state == "GREEN":
            screen.fill(ROUGH)
            pygame.draw.ellipse(screen, GREEN_COLOR, pygame.Rect(curr_w//2 - 200, curr_h//2 - 300, 400, 600))
            pygame.draw.ellipse(screen, GREEN_COLOR, pygame.Rect(curr_w//2 - 350, curr_h//2 - 150, 700, 300))
            
            hole_screen_pos = (curr_w//2, curr_h//2)
            pygame.draw.circle(screen, HOLE_COLOR, hole_screen_pos, 20)
            
            # --- FIXED: Putter Line ---
            if ball.is_dragging:
                # Line from ball to mouse (Slingshot)
                pygame.draw.line(screen, WHITE, (int(ball.putt_x), int(ball.putt_y)), mouse_pos, 2)

            pygame.draw.circle(screen, WHITE, (int(ball.putt_x), int(ball.putt_y)), 10)
            screen.blit(font_med.render("PUTTING: Drag ball BACK to aim at hole", True, WHITE), (40, 40))

        elif state == "HOLE":
            screen.fill((0, 0, 0))
            par = 4
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

            msg1 = font_large.render(f"HOLE FINISHED! PAR {par}", True, WHITE)
            msg2 = font_large.render(f"SCORE: {ball.strokes} ({score_str})", True, YELLOW)
            screen.blit(msg1, (curr_w//2 - msg1.get_width()//2, curr_h//2 - 40))
            screen.blit(msg2, (curr_w//2 - msg2.get_width()//2, curr_h//2 + 10))
            
            msg_restart = font_med.render("Press 'R' to Restart", True, WHITE)
            screen.blit(msg_restart, (curr_w//2 - msg_restart.get_width()//2, curr_h//2 + 80))

        if msg_timer > 0:
            msg_timer -= 1
            surf = font_large.render(msg_text, True, RED)
            bg_rect = surf.get_rect(center=(curr_w//2, curr_h//2 - 100)).inflate(20, 20)
            pygame.draw.rect(screen, WHITE, bg_rect, border_radius=8)
            pygame.draw.rect(screen, HOLE_COLOR, bg_rect, 3, border_radius=8)
            screen.blit(surf, surf.get_rect(center=(curr_w//2, curr_h//2 - 100)))

        pygame.display.flip()
        clock.tick(60)
    pygame.quit()

if __name__ == "__main__":
    main()