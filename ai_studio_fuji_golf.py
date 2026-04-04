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
        # 3D Position
        self.x, self.y, self.z = 0, 0, 0
        self.vx, self.vy = 0, 0
        self.strokes = 0
        self.is_moving = False
        self.flight_progress = 0
        self.flight_duration = 100
        self.max_height = 0
        self.wind_x, self.wind_y = 0, 0
        
        # Putting Attributes (Fixed the missing vars)
        self.putt_x = 0
        self.putt_y = 0
        self.putt_vx = 0
        self.putt_vy = 0
        self.ds = (0, 0) # Drag start position

    def start_flight(self, dist, height, angle, wx, wy):
        self.is_moving = True
        self.flight_progress = 0
        rad = math.radians(angle)
        # Apply slight randomness to power
        actual_dist = dist * random.uniform(0.96, 1.04)
        self.vy = (actual_dist / self.flight_duration) * math.cos(rad)
        self.vx = (actual_dist / self.flight_duration) * math.sin(rad)
        self.max_height = height
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
                self.is_moving = False
                self.z = 0

def project(obj_x, obj_y, obj_z, cam_x, cam_y, w, h):
    rel_y = obj_y - cam_y
    if rel_y < 1: return None
    factor = (h * 0.5) / (rel_y + 15)
    sx = (w // 2) + ((obj_x - cam_x) * factor)
    horizon = h * 0.38
    sy = horizon + (h - horizon) * (15 / (rel_y + 15)) - (obj_z * factor)
    return int(sx), int(sy), factor

def draw_wind_compass(screen, w, h, wx, wy):
    cx, cy = w - 100, 100
    pygame.draw.circle(screen, (0, 0, 0, 100), (cx, cy), 50)
    pygame.draw.circle(screen, WHITE, (cx, cy), 50, 2)
    mag = math.hypot(wx, wy)
    if mag > 0:
        ex = cx + (wx / mag) * 40
        ey = cy - (wy / mag) * 40
        pygame.draw.line(screen, YELLOW, (cx, cy), (ex, ey), 4)
        angle = math.atan2(-(ey-cy), ex-cx)
        p1 = (ex + 10*math.cos(angle+2.5), ey - 10*math.sin(angle+2.5))
        p2 = (ex + 10*math.cos(angle-2.5), ey - 10*math.sin(angle-2.5))
        pygame.draw.polygon(screen, YELLOW, [(ex, ey), p1, p2])
    txt = font_small.render(f"WIND: {int(mag)} MPH", True, WHITE)
    screen.blit(txt, (cx - 45, cy + 55))

def main():
    # --- 1. Difficulty Select ---
    difficulty = None
    while difficulty is None:
        screen.fill((30, 30, 30))
        screen.blit(font_large.render("FUJI GOLF SUCCESSOR", True, WHITE), (WIDTH//2-250, 150))
        screen.blit(font_med.render("Select Difficulty:", True, YELLOW), (WIDTH//2-100, 250))
        screen.blit(font_med.render("1 - Beginner (No Wind)", True, WHITE), (WIDTH//2-150, 310))
        screen.blit(font_med.render("2 - Amateur (8 MPH)", True, WHITE), (WIDTH//2-150, 360))
        screen.blit(font_med.render("3 - Pro (18 MPH)", True, WHITE), (WIDTH//2-150, 410))
        pygame.display.flip()
        for e in pygame.event.get():
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_1: difficulty = 0
                if e.key == pygame.K_2: difficulty = 8
                if e.key == pygame.K_3: difficulty = 18
            if e.type == pygame.QUIT: pygame.quit(); return

    # --- 2. Setup Game ---
    ball = Ball()
    wx = random.uniform(-difficulty, difficulty)
    wy = random.uniform(-difficulty, difficulty)
    cam_x, cam_y = 0, -20
    aim_angle = 0.0
    club_idx = 0
    state = "3D"
    hole_pos = (0, 400)
    fairway_nodes = [(yrd, math.sin(yrd*0.02)*12, 35) for yrd in range(0, 401, 20)]

    running = True
    while running:
        curr_w, curr_h = screen.get_size()
        screen.fill(SKY)
        club = CLUBS[club_idx]
        mouse_pos = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE: running = False
                if event.key == pygame.K_r: main(); return # Restart hole

                if not ball.is_moving and state == "3D":
                    if event.key == pygame.K_w: club_idx = (club_idx - 1) % len(CLUBS)
                    if event.key == pygame.K_s: club_idx = (club_idx + 1) % len(CLUBS)
                    if event.key == pygame.K_SPACE:
                        ball.start_flight(club[1], club[2], aim_angle, wx, wy)
            
            # --- Fixed Putting Logic ---
            if state == "GREEN" and ball.putt_vx == 0 and ball.putt_vy == 0:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    ball.ds = mouse_pos
                if event.type == pygame.MOUSEBUTTONUP:
                    ball.putt_vx = (ball.ds[0] - mouse_pos[0]) * 0.12
                    ball.putt_vy = (ball.ds[1] - mouse_pos[1]) * 0.12
                    ball.strokes += 1

        # Continuous Input
        keys = pygame.key.get_pressed()
        if not ball.is_moving and state == "3D":
            if keys[pygame.K_LEFT]: aim_angle -= 0.7
            if keys[pygame.K_RIGHT]: aim_angle += 0.7

        # --- Physics Update ---
        if state == "3D":
            ball.update()
            cam_x += (ball.x - cam_x) * 0.1
            cam_y += ((ball.y - 18) - cam_y) * 0.1
            # Switch to Green logic
            if not ball.is_moving and math.hypot(ball.x - hole_pos[0], ball.y - hole_pos[1]) < 25:
                state = "GREEN"
                ball.putt_x = curr_w // 2 + (ball.x - hole_pos[0]) * 20
                ball.putt_y = curr_h * 0.2 + (hole_pos[1] - ball.y) * 20

        elif state == "GREEN":
            ball.putt_x += ball.putt_vx
            ball.putt_y += ball.putt_vy
            ball.putt_vx *= 0.97
            ball.putt_vy *= 0.97
            if abs(ball.putt_vx) < 0.1: ball.putt_vx = 0
            if abs(ball.putt_vy) < 0.1: ball.putt_vy = 0
            
            # Hole detection
            d_to_h = math.hypot(ball.putt_x - curr_w//2, ball.putt_y - curr_h*0.2)
            if d_to_h < 18 and math.hypot(ball.putt_vx, ball.putt_vy) < 4:
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
            
            if not ball.is_moving:
                rad = math.radians(aim_angle)
                for i in range(1, 11):
                    dot_y = ball.y + (i * (club[1]/10)); dot_x = ball.x + (i * (club[1]/10) * math.tan(rad))
                    dot_p = project(dot_x, dot_y, 0, cam_x, cam_y, curr_w, curr_h)
                    if dot_p: pygame.draw.circle(screen, YELLOW, (dot_p[0], dot_p[1]), 2)

            b = project(ball.x, ball.y, ball.z, cam_x, cam_y, curr_w, curr_h)
            if b: pygame.draw.circle(screen, WHITE, (b[0], b[1]), max(2, int(10*b[2])))

            draw_wind_compass(screen, curr_w, curr_h, wx, wy)
            screen.blit(font_med.render(f"DISTANCE: {int(math.hypot(ball.x-hole_pos[0], ball.y-hole_pos[1]))} YDS", True, WHITE), (40, 40))
            screen.blit(font_med.render(f"CLUB: {club[0]}", True, YELLOW), (40, 80))
            screen.blit(font_small.render(f"STROKES: {ball.strokes}", True, WHITE), (40, 120))

        elif state == "GREEN":
            screen.fill(GREEN_COLOR)
            pygame.draw.circle(screen, HOLE_COLOR, (curr_w//2, int(curr_h*0.2)), 20)
            if ball.putt_vx == 0: pygame.draw.line(screen, WHITE, (int(ball.putt_x), int(ball.putt_y)), mouse_pos, 1)
            pygame.draw.circle(screen, WHITE, (int(ball.putt_x), int(ball.putt_y)), 10)
            screen.blit(font_med.render("PUTTING: Slingshot toward hole", True, WHITE), (40, 40))

        elif state == "HOLE":
            screen.fill((0, 0, 0))
            diff = ball.strokes - 4
            terms = {-2: "EAGLE!", -1: "BIRDIE!", 0: "PAR", 1: "BOGEY", 2: "DBL BOGEY"}
            res = terms.get(diff, "HOLE FINISHED")
            screen.blit(font_large.render(res, True, YELLOW), (curr_w//2-120, curr_h//2-50))
            screen.blit(font_med.render(f"Final Strokes: {ball.strokes} | Press 'R' to reset", True, WHITE), (curr_w//2-180, curr_h//2+30))

        pygame.display.flip()
        clock.tick(60)
    pygame.quit()

if __name__ == "__main__":
    main()