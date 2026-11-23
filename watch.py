"""
Watch GAIA live (Pygame 60 FPS viewer by default).

    python watch.py                      open the Pygame viewer
    python watch.py --paused             open paused (press Space or Play)
    python watch.py --demo               schedule a drought and a plague
    python watch.py --matplotlib         use the original Matplotlib viewer
    python watch.py --png frame.png --turns 300    save a static picture
"""

import argparse


def parse_args():
    parser = argparse.ArgumentParser(description="GAIA live viewer")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--size", type=int, default=120, help="world width and height")
    parser.add_argument("--speed", type=int, default=4,
                        help="turns per second (default: 4 for smooth viewing)")
    parser.add_argument("--paused", action="store_true", help="start paused")
    parser.add_argument("--demo", action="store_true",
                        help="schedule a drought (turn 200) and a plague (turn 350)")
    parser.add_argument("--no-seasons", action="store_true")
    parser.add_argument("--matplotlib", action="store_true",
                        help="use the legacy Matplotlib viewer")
    parser.add_argument("--png", metavar="FILE",
                        help="don't open a window; run --turns turns and save a picture")
    parser.add_argument("--turns", type=int, default=0,
                        help="turns to run before showing / saving")
    return parser.parse_args()


def main():
    args = parse_args()

    from run_gaia import build_simulation
    from Simulation.stress import Drought, Plague

    events = []
    if args.demo:
        events = [Drought(start=200, duration=60, severity=0.3),
                  Plague(start=350, species="Grazer", fraction=0.7)]

    sim, recorder, stress = build_simulation(
        seed=args.seed, events=events, size=args.size, seasons=not args.no_seasons)

    if args.png or args.matplotlib:
        import matplotlib
        if args.png:
            matplotlib.use("Agg")
        from Interface.viewer import SimulationViewer, SPEEDS

        nearest = min((i for i, v in enumerate(SPEEDS) if v != "max"),
                      key=lambda i: abs(SPEEDS[i] - args.speed))
        viewer = SimulationViewer(sim, recorder=recorder, speed_index=nearest,
                                  start_paused=args.paused or bool(args.png))
        if args.turns:
            viewer.step(args.turns)
        if args.png:
            viewer.save_png(args.png)
            print(f"saved {args.png} (turn {sim.world.turn})")
        else:
            viewer.paused = args.paused
            viewer._update_speed_text()
            viewer.show()
    else:
        from Interface.pygame_viewer import PygameViewer, SPEEDS

        nearest = min((i for i, v in enumerate(SPEEDS) if v != "max"),
                      key=lambda i: abs(SPEEDS[i] - args.speed))
        viewer = PygameViewer(sim, recorder=recorder, stress=stress,
                              speed_index=nearest, start_paused=args.paused)
        if args.turns:
            viewer._advance(args.turns)
        viewer.show()


if __name__ == "__main__":
    main()