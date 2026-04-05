import pygame
import math
import random

# --- Window Setup ---
WIDTH, HEIGHT = 1280, 720 
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption("Meigs Field Golf Course")

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

def generate_course():
    course = []
    # Hole 1: Par 4, 400y (S-Curve)
    course.append({
        "par": 4, "hole_pos": (0, 400), 
        "fairway": [(y, math.sin(y*0.02)*12, 35) for y in range(40, 401, 20)],
        "green": ((45, 60), (70, 30), (10, -5))
    })
    # Hole 2: Par 3, 180y (Short, angled slightly right)
    course.append({
        "par": 3, "hole_pos": (20, 180), 
        "fairway": [(y, y*0.1, 25) for y in range(20, 181, 20)],
        "green": ((35, 50), (55, 25), (-5, 10))
    })
    # Hole 3: Par 5, 550y (Dogleg left)
    course.append({
        "par": 5, "hole_pos": (-80, 550), 
        "fairway": [(y, -math.pow(y/100, 2)*2.5, 35) for y in range(40, 551, 20)],
        "green": ((45, 45), (65, 35), (0, 0))
    })
    # Generate remaining 15 holes to make a full 18
    pars = [4, 4, 3, 4, 5, 4, 4, 3, 4, 5, 4, 4, 3, 5, 4]
    for i, p in enumerate(pars):
        if p == 3: dist = random.randint(140, 200)
        elif p == 4: dist = random.randint(350, 450)
        else: dist = random.randint(500, 600)
        curve_dir = 12 if i % 2 == 0 else -12
        
        gw1, gh1 = random.uniform(40, 70), random.uniform(50, 90)
        gw2, gh2 = random.uniform(60, 100), random.uniform(25, 50)
        ox, oy = random.uniform(-25, 25), random.uniform(-25, 25)
        course.append({
            "par": p, "hole_pos": (math.sin(dist*0.01)*curve_dir, dist), 
            "fairway": [(y, math.sin(y*0.01)*curve_dir, 30) for y in range(40, dist+1, 20)],
            "green": ((gw1, gh1), (gw2, gh2), (ox, oy))
        })
    return course

COURSE = generate_course()

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
        # Reduced base dampening to prevent 400+ yard driver rolls
        dist_damp = 0.15 - ((self.rpm - 2000) / 10000.0) 
        dist_damp = max(-0.15, min(0.25, dist_damp))
        
        height_damp = 0.2 + (self.loft_offset / 120.0)
        height_damp = max(0.1, min(0.3, height_damp))
        
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

def draw_hud(screen, curr_w, curr_h, ball, hole_pos, club_idx, power, wx, wy, is_swinging, trajectory_offset, cam_angle, hole_idx, par):
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
    screen.blit(font_med.render(f"LIE: {ball.lie}%", True, WHITE if ball.lie >= 90 else YELLOW), (curr_w - 280, 154))
    loft_str = f"+{int(trajectory_offset)}" if trajectory_offset > 0 else str(int(trajectory_offset))
    screen.blit(font_med.render(f"LOFT: {loft_str}°", True, WHITE), (curr_w - 280, 194))
    
    display_rpm = ball.rpm if ball.is_moving else max(500, int(2000 + (club_idx * 300) + (trajectory_offset * 150)))
    screen.blit(font_med.render(f"SPIN: {display_rpm} RPM", True, WHITE), (curr_w - 280, 234))
    
    # Wind Compass
    cx, cy = curr_w - 80, 310
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

def draw_menus(screen, curr_w, active_menu, show_wind_preview):
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
        pygame.draw.rect(screen, (220, 220, 220), (60, 24, 200, 60))
        pygame.draw.rect(screen, (100, 100, 100), (60, 24, 200, 60), 1)
        chk = "[X]" if show_wind_preview else "[ ]"
        screen.blit(font_small.render(f"{chk} Wind Preview", True, (0, 0, 0)), (70, 28))
        screen.blit(font_small.render("    View Scorecard (C)", True, (0, 0, 0)), (70, 54))

def draw_scorecard(screen, curr_w, curr_h, scores, course):
    overlay = pygame.Surface((curr_w, curr_h), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 180))
    screen.blit(overlay, (0, 0))

    sw, sh = 820, 360
    sx, sy = curr_w//2 - sw//2, curr_h//2 - sh//2
    pygame.draw.rect(screen, (240, 240, 240), (sx, sy, sw, sh), border_radius=10)
    pygame.draw.rect(screen, HOLE_COLOR, (sx, sy, sw, sh), 4, border_radius=10)

    title = font_large.render("SCORECARD", True, HOLE_COLOR)
    screen.blit(title, (curr_w//2 - title.get_width()//2, sy + 15))

    def draw_grid(x, y, start_hole, end_hole, label_total1, label_total2=None):
        col_w = 55
        cols = 12 if label_total2 else 11
        
        pygame.draw.rect(screen, (200, 200, 200), (x, y, col_w * cols, 30))
        
        headers = ["HOLE"] + [str(i+1) for i in range(start_hole, end_hole)] + [label_total1]
        if label_total2: headers.append(label_total2)
        for i, h_txt in enumerate(headers):
            surf = font_small.render(h_txt, True, HOLE_COLOR)
            screen.blit(surf, (x + i*col_w + col_w//2 - surf.get_width()//2, y + 6))
            
        y += 30
        out_par = sum(c["par"] for c in course[start_hole:end_hole])
        pars = ["PAR"] + [str(course[i]["par"]) for i in range(start_hole, end_hole)] + [str(out_par)]
        if label_total2: pars.append(str(sum(c["par"] for c in course)))
        for i, p_txt in enumerate(pars):
            surf = font_small.render(p_txt, True, HOLE_COLOR)
            screen.blit(surf, (x + i*col_w + col_w//2 - surf.get_width()//2, y + 6))
            
        y += 30
        out_score = sum(scores[i] for i in range(start_hole, end_hole) if scores[i] is not None)
        out_score_txt = str(out_score) if any(scores[i] is not None for i in range(start_hole, end_hole)) else "-"
        
        s_row = ["SCORE"] + [str(scores[i]) if scores[i] is not None else "-" for i in range(start_hole, end_hole)] + [out_score_txt]
        if label_total2:
            tot = sum(s for s in scores if s is not None)
            s_row.append(str(tot) if any(s is not None for s in scores) else "-")

        for i, s_txt in enumerate(s_row):
            color = HOLE_COLOR
            if i > 0 and i <= (end_hole - start_hole) and s_txt != "-":
                diff = int(s_txt) - course[start_hole + i - 1]["par"]
                if diff < 0: color = RED
                elif diff > 0: color = (0, 0, 200)
            surf = font_small.render(s_txt, True, color)
            screen.blit(surf, (x + i*col_w + col_w//2 - surf.get_width()//2, y + 6))
            
        for r in range(4): pygame.draw.line(screen, GRAY, (x, y - 60 + r*30), (x + cols*col_w, y - 60 + r*30))
        for c in range(cols + 1): pygame.draw.line(screen, GRAY, (x + c*col_w, y - 60), (x + c*col_w, y + 30))

    draw_grid(curr_w//2 - (55*11)//2, sy + 90, 0, 9, "OUT")
    draw_grid(curr_w//2 - (55*12)//2, sy + 210, 9, 18, "IN", "TOT")
    
    close_txt = font_small.render("Press 'C' to Close Scorecard", True, GRAY)
    screen.blit(close_txt, (curr_w//2 - close_txt.get_width()//2, sy + 320))

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
        
        title = font_large.render("MEIGS FIELD GOLF COURSE", True, WHITE)
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

    hole_idx = 0
    scores = [None] * 18
    hole_data = COURSE[hole_idx]
    hole_pos = hole_data["hole_pos"]
    fairway_nodes = hole_data["fairway"]
    par = hole_data["par"]
    green_shape = hole_data["green"]

    ball = Ball()
    wx, wy = random.uniform(-difficulty, difficulty), random.uniform(-difficulty, difficulty)
    cam_x, cam_y = 0, -20
    cam_angle = 0.0
    aim_angle = 0.0
    trajectory_offset = 0.0
    show_wind_preview = False
    show_scorecard = False
    club_idx = 0
    state = "3D"
    
    is_swinging = False
    power = 0.0
    msg_text = ""
    msg_timer = 0
    active_menu = None

    running = True
    while running:
        curr_w, curr_h = screen.get_size()
        mouse_pos = pygame.mouse.get_pos()
        screen.fill(SKY)

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
                elif active_menu == "Options" and pygame.Rect(60, 24, 200, 60).collidepoint(event.pos):
                    if event.pos[1] < 54: show_wind_preview = not show_wind_preview
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
                
                if not ball.is_moving and state == "3D":
                    if event.key == pygame.K_w: club_idx = (club_idx - 1) % len(CLUBS)
                    if event.key == pygame.K_s: club_idx = (club_idx + 1) % len(CLUBS)
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

            if state == "HOLE":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    show_scorecard = False
                    hole_idx += 1
                    if hole_idx >= len(COURSE):
                        main() # Restart game if 18 holes are finished
                        return
                    hole_data = COURSE[hole_idx]
                    hole_pos = hole_data["hole_pos"]
                    fairway_nodes = hole_data["fairway"]
                    par = hole_data["par"]
                    green_shape = hole_data["green"]
                    ball = Ball()
                    wx, wy = random.uniform(-difficulty, difficulty), random.uniform(-difficulty, difficulty)
                    cam_x, cam_y = 0, -20
                    cam_angle, aim_angle, trajectory_offset = 0.0, 0.0, 0.0
                    state = "3D"
                    is_swinging = False; power = 0.0

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
                # Find nearest fairway node to determine boundaries dynamically
                closest_x = 0
                closest_w = 30
                min_dist = 9999
                for y, x, w in fairway_nodes:
                    if abs(y - ball.y) < min_dist:
                        min_dist = abs(y - ball.y)
                        closest_x = x
                        closest_w = w
                        
                if abs(ball.x - closest_x) > 80 or ball.y < -50 or ball.y > hole_pos[1] + 50:
                    ball.strokes += 2
                    ball.x, ball.y = ball.prev_x, ball.prev_y
                    msg_text = "OUT OF BOUNDS! +2 STROKES"
                    msg_timer = 180
                elif math.hypot(ball.x - hole_pos[0], ball.y - hole_pos[1]) < 75:
                    state = "GREEN"
                    ball.putt_x = curr_w // 2 + (ball.x - hole_pos[0]) * 10
                    ball.putt_y = curr_h // 2 + (hole_pos[1] - ball.y) * 10
                    ball.lie = 100
                else:
                    if abs(ball.x - closest_x) <= closest_w:
                        ball.lie = 100
                    else:
                        ball.lie = random.randint(20, 100)

        elif state == "GREEN":
            ball.putt_x += ball.putt_vx; ball.putt_y += ball.putt_vy
            ball.putt_vx *= 0.97; ball.putt_vy *= 0.97
            if abs(ball.putt_vx) < 0.05 and abs(ball.putt_vy) < 0.05: 
                ball.putt_vx = ball.putt_vy = 0
            
            hole_cx, hole_cy = curr_w // 2, curr_h // 2
            dist_to_hole = math.hypot(ball.putt_x - hole_cx, ball.putt_y - hole_cy)
            speed = math.hypot(ball.putt_vx, ball.putt_vy)
            
            # Physics around the hole (Lip in/out)
            if 0 < dist_to_hole < 26:
                # Apply gravity pulling the ball towards the center of the hole
                pull_strength = (26 - dist_to_hole) * 0.12
                ball.putt_vx += ((hole_cx - ball.putt_x) / dist_to_hole) * pull_strength
                ball.putt_vy += ((hole_cy - ball.putt_y) / dist_to_hole) * pull_strength
                
                # Faster putts need to hit closer to dead-center to drop
                drop_threshold = max(4.0, 20.0 - (speed * 3.0))
                if dist_to_hole < drop_threshold:
                    state = "HOLE"
                    scores[hole_idx] = ball.strokes
                    show_scorecard = True

        # --- Rendering ---
        if state == "3D":
            pygame.draw.rect(screen, BROWN, (0, int(curr_h*0.38), curr_w, curr_h))
            
            rough_nodes = [(yrd, 0, 250) for yrd in range(-100, int(hole_pos[1] + 100), 50)]
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
                    pygame.draw.circle(screen, RED, tm1[:2], max(1, int(0.2*tm1[2])))
                    pygame.draw.circle(screen, WHITE, tm1[:2], max(1, int(0.2*tm1[2])), 1)
                if tm2: 
                    pygame.draw.circle(screen, RED, tm2[:2], max(1, int(0.2*tm2[2])))
                    pygame.draw.circle(screen, WHITE, tm2[:2], max(1, int(0.2*tm2[2])), 1)

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
            g1_w, g1_h = green_shape[0]
            g2_w, g2_h = green_shape[1]
            ox, oy = green_shape[2]
            for a in range(0, 360, 10):
                rad = math.radians(a)
                gp1 = project(hole_pos[0] + math.cos(rad)*g1_w, hole_pos[1] + math.sin(rad)*g1_h, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if gp1: green1_pts.append(gp1[:2])
                gp2 = project(hole_pos[0] + ox + math.cos(rad)*g2_w, hole_pos[1] + oy + math.sin(rad)*g2_h, 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
                if gp2: green2_pts.append(gp2[:2])
            if len(green1_pts) > 2: pygame.draw.polygon(screen, GREEN_COLOR, green1_pts)
            if len(green2_pts) > 2: pygame.draw.polygon(screen, GREEN_COLOR, green2_pts)

            f = project(hole_pos[0], hole_pos[1], 0, cam_x, cam_y, cam_angle, curr_w, curr_h)
            if f:
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
                        
                        cw = max(1, int((1.0 - club_idx * 0.04) * club_head[2]))
                        ch = max(1, int((0.8 if club_idx <= 2 else 0.25) * club_head[2]))
                        club_rect = pygame.Rect(club_head[0]-cw, club_head[1]-ch, cw*2, ch*2)
                        pygame.draw.ellipse(screen, (100, 100, 100), club_rect)

            b = project(ball.x, ball.y, ball.z, cam_x, cam_y, cam_angle, curr_w, curr_h)
            if b: pygame.draw.circle(screen, WHITE, (b[0], b[1]), max(1, int(0.15*b[2])))

            # --- Aim Indicator ---
            if not ball.is_moving:
                lie_mult = ball.lie / 100.0
                adj_dist = (CLUBS[club_idx][1] - (trajectory_offset * 2.5)) * lie_mult
                adj_height = (CLUBS[club_idx][2] + (trajectory_offset * 1.5)) * lie_mult
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

            draw_hud(screen, curr_w, curr_h, ball, hole_pos, club_idx, power, wx, wy, is_swinging, trajectory_offset, cam_angle, hole_idx, par)

        elif state == "GREEN":
            screen.fill(ROUGH)
            g1_w, g1_h = green_shape[0]
            g2_w, g2_h = green_shape[1]
            ox, oy = green_shape[2]
            pygame.draw.ellipse(screen, GREEN_COLOR, pygame.Rect(curr_w//2 - int(g1_w*10), curr_h//2 - int(g1_h*10), int(g1_w*20), int(g1_h*20)))
            pygame.draw.ellipse(screen, GREEN_COLOR, pygame.Rect(curr_w//2 + int(ox*10) - int(g2_w*10), curr_h//2 - int(oy*10) - int(g2_h*10), int(g2_w*20), int(g2_h*20)))
            
            hole_screen_pos = (curr_w//2, curr_h//2)
            pygame.draw.circle(screen, HOLE_COLOR, hole_screen_pos, 12)
            
            # --- FIXED: Putter Line ---
            if ball.is_dragging:
                # Line from ball to mouse (Slingshot)
                pygame.draw.line(screen, WHITE, (int(ball.putt_x), int(ball.putt_y)), mouse_pos, 2)

            pygame.draw.circle(screen, WHITE, (int(ball.putt_x), int(ball.putt_y)), 6)
            screen.blit(font_med.render("PUTTING: Drag ball BACK to aim at hole", True, WHITE), (40, 40))

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
            
            msg_restart = font_med.render("Press SPACE for Next Hole", True, WHITE)
            screen.blit(msg_restart, (curr_w//2 - msg_restart.get_width()//2, curr_h//2 + 100))

        if msg_timer > 0:
            msg_timer -= 1
            surf = font_large.render(msg_text, True, RED)
            bg_rect = surf.get_rect(center=(curr_w//2, curr_h//2 - 100)).inflate(20, 20)
            pygame.draw.rect(screen, WHITE, bg_rect, border_radius=8)
            pygame.draw.rect(screen, HOLE_COLOR, bg_rect, 3, border_radius=8)
            screen.blit(surf, surf.get_rect(center=(curr_w//2, curr_h//2 - 100)))

        draw_menus(screen, curr_w, active_menu, show_wind_preview)
        
        if show_scorecard:
            draw_scorecard(screen, curr_w, curr_h, scores, COURSE)

        pygame.display.flip()
        clock.tick(60)
    pygame.quit()

if __name__ == "__main__":
    main()