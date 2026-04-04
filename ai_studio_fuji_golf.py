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
        
        self.prev_x, self.prev_y = 0, 0
        self.lie = 100
        # Putting state
        self.putt_x = 0
        self.putt_y = 0
        self.putt_vx = 0
        self.putt_vy = 0
        self.ds = None # Drag start
        self.is_dragging = False

    def start_flight(self, dist, height, angle, wx, wy, power_mult):
        self.prev_x, self.prev_y = self.x, self.y
        self.is_moving = True
        self.flight_progress = 0
        rad = math.radians(angle)
        actual_dist = (dist * power_mult) * random.uniform(0.98, 1.02)
        self.vy = (actual_dist / self.flight_duration) * math.cos(rad)
        self.vx = (actual_dist / self.flight_duration) * math.sin(rad)
        self.max_height = height * power_mult
        self.wind_x, self.wind_y = wx / 70.0, wy / 70.0
        self.strokes += 1

    def update(self):
        if self.is_moving:
            self.flight_progress += 1
            self.x += self.vx + self.wind_x
            self.y += self.vy + self.wind_y
            t = self.flight_progress / self.flight_duration
            self.z = 4 * self.max_height * t * (1 - t)
            if self.flight_progress >= self.flight_duration:
                self.is_moving = False; self.z = 0

def project(obj_x, obj_y, obj_z, cam_x, cam_y, w, h):
    rel_y = obj_y - cam_y
    if rel_y < 1: return None
    factor = (h * 0.5) / (rel_y + 15)
    sx = (w // 2) + ((obj_x - cam_x) * factor)
    horizon = h * 0.38
    sy = horizon + (h - horizon) * (15 / (rel_y + 15)) - (obj_z * factor)
    return int(sx), int(sy), factor

def draw_hud(screen, curr_w, curr_h, ball, hole_pos, club_idx, power, wx, wy, is_swinging, trajectory_offset):
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
    
    # Wind Compass
    cx, cy = curr_w - 80, 150
    pygame.draw.circle(screen, WHITE, (cx, cy), 40, 2)
    mag = math.hypot(wx, wy)
    if mag > 0:
        ex, ey = cx + (wx/mag)*35, cy - (wy/mag)*35
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
    aim_angle = 0.0
    trajectory_offset = 0.0
    club_idx = 0
    state = "3D"
    hole_pos = (0, 400)
    fairway_nodes = [(yrd, math.sin(yrd*0.02)*12, 35) for yrd in range(0, 401, 20)]
    
    is_swinging = False
    power = 0.0

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
                    if event.key == pygame.K_SPACE:
                        is_swinging = True; power = 0.0

            if event.type == pygame.KEYUP:
                if event.key == pygame.K_SPACE and is_swinging:
                    effective_power = power * (ball.lie / 100.0)
                    dist = CLUBS[club_idx][1] - (trajectory_offset * 2.5)
                    height = CLUBS[club_idx][2] + (trajectory_offset * 1.5)
                    ball.start_flight(dist, height, aim_angle, wx, wy, effective_power)
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
            ball.update()
            cam_x += (ball.x - cam_x) * 0.1
            cam_y += ((ball.y - 18) - cam_y) * 0.1
            if not ball.is_moving and math.hypot(ball.x - hole_pos[0], ball.y - hole_pos[1]) < 25:
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
            pygame.draw.rect(screen, ROUGH, (0, int(curr_h*0.38), curr_w, curr_h))
            for i in range(len(fairway_nodes)-1):
                y1, x1, w1 = fairway_nodes[i]; y2, x2, w2 = fairway_nodes[i+1]
                p1l = project(x1-w1, y1, 0, cam_x, cam_y, curr_w, curr_h)
                p1r = project(x1+w1, y1, 0, cam_x, cam_y, curr_w, curr_h)
                p2l = project(x2-w2, y2, 0, cam_x, cam_y, curr_w, curr_h)
                p2r = project(x2+w2, y2, 0, cam_x, cam_y, curr_w, curr_h)
                if p1l and p2l: pygame.draw.polygon(screen, FAIRWAY, [p1l[:2], p1r[:2], p2r[:2], p2l[:2]])

            # Draw Green circle
            green_pts = []
            for a in range(0, 360, 30):
                gp = project(hole_pos[0]+math.cos(math.radians(a))*30, hole_pos[1]+math.sin(math.radians(a))*30, 0, cam_x, cam_y, curr_w, curr_h)
                if gp: green_pts.append(gp[:2])
            if len(green_pts) > 3: pygame.draw.polygon(screen, GREEN_COLOR, green_pts)

            f = project(hole_pos[0], hole_pos[1], 0, cam_x, cam_y, curr_w, curr_h)
            if f:
                pygame.draw.line(screen, WHITE, (f[0], f[1]), (f[0], f[1]-int(90*f[2])), 2)
                pygame.draw.rect(screen, RED, (f[0], f[1]-int(90*f[2]), int(20*f[2]), int(15*f[2])))
            
            b = project(ball.x, ball.y, ball.z, cam_x, cam_y, curr_w, curr_h)
            if b: pygame.draw.circle(screen, WHITE, (b[0], b[1]), max(2, int(10*b[2])))

            # --- Aim Indicator ---
            if not ball.is_moving:
                adj_dist = CLUBS[club_idx][1] - (trajectory_offset * 2.5)
                adj_height = CLUBS[club_idx][2] + (trajectory_offset * 1.5)
                target_x = ball.x + adj_dist * math.sin(math.radians(aim_angle))
                target_y = ball.y + adj_dist * math.cos(math.radians(aim_angle))
                t_proj = project(target_x, target_y, 0, cam_x, cam_y, curr_w, curr_h)
                
                arc_points = []
                for step in range(16):
                    t = step / 15.0
                    px = ball.x + (target_x - ball.x) * t
                    py = ball.y + (target_y - ball.y) * t
                    pz = 4 * adj_height * t * (1 - t)
                    proj_pt = project(px, py, pz, cam_x, cam_y, curr_w, curr_h)
                    if proj_pt:
                        arc_points.append(proj_pt[:2])
                        
                if len(arc_points) > 1:
                    pygame.draw.lines(screen, YELLOW, False, arc_points, 1)

                if b and t_proj:
                    pygame.draw.circle(screen, YELLOW, (t_proj[0], t_proj[1]), max(2, int(15*t_proj[2])), 1)

            draw_hud(screen, curr_w, curr_h, ball, hole_pos, club_idx, power, wx, wy, is_swinging, trajectory_offset)

        elif state == "GREEN":
            screen.fill(ROUGH)
            pygame.draw.ellipse(screen, GREEN_COLOR, pygame.Rect(curr_w//2 - 200, curr_h//2 - 300, 400, 600))
            pygame.draw.ellipse(screen, GREEN_COLOR, pygame.Rect(curr_w//2 - 350, curr_h//2 - 100, 700, 300))
            
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

        pygame.display.flip()
        clock.tick(60)
    pygame.quit()

if __name__ == "__main__":
    main()