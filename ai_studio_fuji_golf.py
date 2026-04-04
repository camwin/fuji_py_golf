import pygame
import math
import random

# --- Window Setup ---
WIDTH, HEIGHT = 1280, 720 
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption("Fuji Golf Successor")

clock = pygame.time.Clock()
font_large = pygame.font.SysFont("Verdana", 40, bold=True)
font_med = pygame.font.SysFont("Verdana", 24, bold=True)
font_small = pygame.font.SysFont("Verdana", 18, bold=True)

# --- Colors ---
ROUGH = (20, 70, 20)
FAIRWAY = (40, 140, 40)
GREEN_COLOR = (60, 180, 60)
SKY = (135, 206, 235)
WHITE = (255, 255, 255)
HOLE_COLOR = (10, 10, 10)
RED = (200, 0, 0)
YELLOW = (255, 255, 0)

# --- Clubs & Scoring ---
CLUBS = [
    ["Driver", 260, 30], ["3 Wood", 235, 35], ["5 Wood", 215, 40],
    ["3 Iron", 200, 45], ["4 Iron", 190, 50], ["5 Iron", 180, 55],
    ["6 Iron", 170, 60], ["7 Iron", 160, 65], ["8 Iron", 150, 70],
    ["9 Iron", 140, 75], ["PW", 125, 85], ["GW", 110, 95],
    ["SW", 95, 100], ["LW", 75, 110]
]

def get_score_term(strokes, par):
    diff = strokes - par
    terms = {
        -3: "ALBATROSS!",
        -2: "EAGLE!",
        -1: "BIRDIE!",
        0: "PAR",
        1: "BOGEY",
        2: "DOUBLE BOGEY",
        3: "TRIPLE BOGEY"
    }
    return terms.get(diff, f"+{diff} Score")

class Ball:
    def __init__(self):
        self.x, self.y, self.z = 0, 0, 0
        self.vx, self.vy = 0, 0
        self.strokes = 0
        self.is_moving = False
        self.flight_progress = 0
        self.flight_duration = 100
        self.max_height = 0
        self.putt_vx, self.putt_vy = 0, 0

    def start_flight(self, dist, height, angle, wind_x, wind_y):
        self.is_moving = True
        self.flight_progress = 0
        rad = math.radians(angle)
        self.vy = (dist / self.flight_duration) * math.cos(rad)
        self.vx = (dist / self.flight_duration) * math.sin(rad)
        self.max_height = height
        self.current_wind_x = wind_x / 80.0
        self.current_wind_y = wind_y / 80.0
        self.strokes += 1

    def update(self):
        if self.is_moving:
            self.flight_progress += 1
            self.x += self.vx + self.current_wind_x
            self.y += self.vy + self.current_wind_y
            t = self.flight_progress / self.flight_duration
            self.z = 4 * self.max_height * t * (1 - t)
            if self.flight_progress >= self.flight_duration:
                self.is_moving = False; self.z = 0

def project(obj_x, obj_y, obj_z, cam_x, cam_y, w, h):
    rel_y = obj_y - cam_y
    if rel_y < 1: return None
    factor = (h * 0.5) / (rel_y + 15)
    sx = (w // 2) + ((obj_x - cam_x) * factor)
    horizon = h * 0.35
    sy = horizon + (h - horizon) * (15 / (rel_y + 15)) - (obj_z * factor)
    return int(sx), int(sy), factor

def main():
    # Difficulty / Wind Setup
    wind_x, wind_y = random.uniform(-8, 8), random.uniform(-8, 8)
    ball = Ball()
    cam_x, cam_y = 0, -20
    aim_angle = 0.0
    club_idx = 0
    state = "3D"
    
    hole_pos = (0, 400)
    # Generate Fairway Ribs
    fairway_pts = []
    for yrd in range(0, 420, 20):
        # Slightly wobble the fairway for "shape"
        wobble = math.sin(yrd * 0.02) * 15
        width = 35 if yrd < 350 else 0 # Fairway narrows into the green
        fairway_pts.append((yrd, wobble, width))

    running = True
    while running:
        curr_w, curr_h = screen.get_size()
        screen.fill(SKY)
        club = CLUBS[club_idx]

        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE: running = False
                if not ball.is_moving and state == "3D":
                    if event.key == pygame.K_w: club_idx = (club_idx - 1) % len(CLUBS)
                    if event.key == pygame.K_s: club_idx = (club_idx + 1) % len(CLUBS)
                    if event.key == pygame.K_SPACE:
                        ball.start_flight(club[1], club[2], aim_angle, wind_x, wind_y)
            
            if state == "GREEN" and ball.putt_vx == 0:
                if event.type == pygame.MOUSEBUTTONDOWN: ball.drag_s = pygame.mouse.get_pos()
                if event.type == pygame.MOUSEBUTTONUP:
                    m = pygame.mouse.get_pos()
                    ball.putt_vx = (ball.drag_s[0]-m[0])*0.12; ball.putt_vy = (ball.drag_s[1]-m[1])*0.12
                    ball.strokes += 1

        # Logic
        keys = pygame.key.get_pressed()
        if not ball.is_moving and state == "3D":
            if keys[pygame.K_LEFT]: aim_angle -= 0.8
            if keys[pygame.K_RIGHT]: aim_angle += 0.8

        if state == "3D":
            ball.update()
            cam_x += (ball.x - cam_x) * 0.1
            cam_y += ((ball.y - 20) - cam_y) * 0.1
            
            if not ball.is_moving and math.hypot(ball.x - hole_pos[0], ball.y - hole_pos[1]) < 25:
                state = "GREEN"
                ball.putt_x = curr_w//2 + (ball.x - hole_pos[0])*20
                ball.putt_y = curr_h*0.2 + (hole_pos[1]-ball.y)*20

        # Rendering 3D
        if state == "3D":
            pygame.draw.rect(screen, ROUGH, (0, curr_h*0.35, curr_w, curr_h*0.65))
            
            # 1. Draw Fairway segments
            for i in range(len(fairway_pts)-1):
                y1, wob1, w1 = fairway_pts[i]
                y2, wob2, w2 = fairway_pts[i+1]
                p1l = project(wob1-w1, y1, 0, cam_x, cam_y, curr_w, curr_h)
                p1r = project(wob1+w1, y1, 0, cam_x, cam_y, curr_w, curr_h)
                p2l = project(wob2-w2, y2, 0, cam_x, cam_y, curr_w, curr_h)
                p2r = project(wob2+w2, y2, 0, cam_x, cam_y, curr_w, curr_h)
                if p1l and p2l:
                    pygame.draw.polygon(screen, FAIRWAY, [p1l[:2], p1r[:2], p2r[:2], p2l[:2]])

            # 2. Draw Green (The landing area)
            green_poly = []
            for a in range(0, 360, 30):
                gx = hole_pos[0] + math.cos(math.radians(a)) * 25
                gy = hole_pos[1] + math.sin(math.radians(a)) * 25
                gp = project(gx, gy, 0, cam_x, cam_y, curr_w, curr_h)
                if gp: green_poly.append(gp[:2])
            if len(green_poly) > 3: pygame.draw.polygon(screen, GREEN_COLOR, green_poly)

            # 3. Draw Flag
            f = project(hole_pos[0], hole_pos[1], 0, cam_x, cam_y, curr_w, curr_h)
            if f:
                pygame.draw.line(screen, WHITE, (f[0], f[1]), (f[0], f[1]-100*f[2]), 2)
                pygame.draw.rect(screen, RED, (f[0], f[1]-100*f[2], 20*f[2], 15*f[2]))

            # 4. Draw Ball Shadow & Ball
            shadow = project(ball.x, ball.y, 0, cam_x, cam_y, curr_w, curr_h)
            if shadow: pygame.draw.circle(screen, (0, 40, 0, 100), (shadow[0], shadow[1]), max(1, int(8*shadow[2])))
            b = project(ball.x, ball.y, ball.z, cam_x, cam_y, curr_w, curr_h)
            if b: pygame.draw.circle(screen, WHITE, (b[0], b[1]), max(2, int(10*b[2])))

            # HUD
            dist = int(math.hypot(ball.x-hole_pos[0], ball.y-hole_pos[1]))
            screen.blit(font_large.render(f"{dist} Yds", True, WHITE), (40, 40))
            screen.blit(font_med.render(f"{club[0]} | Strokes: {ball.strokes}", True, WHITE), (40, 100))
            # Wind
            pygame.draw.line(screen, YELLOW, (curr_w-80, 80), (curr_w-80+wind_x*5, 80-wind_y*5), 3)

        elif state == "GREEN":
            screen.fill(GREEN_COLOR)
            pygame.draw.circle(screen, HOLE_COLOR, (curr_w//2, int(curr_h*0.2)), 20)
            pygame.draw.circle(screen, WHITE, (int(ball.putt_x), int(ball.putt_y)), 10)
            ball.putt_x += ball.putt_vx; ball.putt_y += ball.putt_vy
            ball.putt_vx *= 0.97; ball.putt_vy *= 0.97
            if math.hypot(ball.putt_x - curr_w//2, ball.putt_y - curr_h*0.2) < 15: state = "HOLE"

        elif state == "HOLE":
            screen.fill((0, 0, 0))
            term = get_score_term(ball.strokes, 4)
            msg = font_large.render(f"{term}", True, YELLOW)
            sub = font_med.render(f"Finished in {ball.strokes} strokes", True, WHITE)
            screen.blit(msg, (curr_w//2 - msg.get_width()//2, curr_h//2 - 40))
            screen.blit(sub, (curr_w//2 - sub.get_width()//2, curr_h//2 + 40))

        pygame.display.flip()
        clock.tick(60)
    pygame.quit()

if __name__ == "__main__":
    main()