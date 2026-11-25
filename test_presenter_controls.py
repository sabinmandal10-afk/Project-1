import pygame
pygame.init()
pygame.display.set_mode((1, 1), pygame.HIDDEN)

from run_gaia import build_simulation
from Interface.pygame_viewer import PygameViewer
from Interface.showcase import ShowcaseDirector
import Interface.education as edu

sim, recorder, stress = build_simulation(seed=1, size=100)
viewer = PygameViewer(sim, recorder=recorder, stress=stress, showcase=False)

# 1. Test director steps
print("Testing ShowcaseDirector steps...")
assert len(viewer.director.steps) == len(edu.SHOWCASE), f"Expected {len(edu.SHOWCASE)} steps, got {len(viewer.director.steps)}"
for i, step in enumerate(viewer.director.steps):
    assert step.speaker_note != "", f"Step {i} ({step.title}) missing speaker note"
print("All steps have speaker notes!")

# 2. Test showcase start
print("Testing showcase start...")
viewer._start_showcase()
assert viewer.showcase_on == True
assert viewer._showcase_idx == 0
assert viewer.caption is not None
assert viewer.caption["title"] == edu.SHOWCASE[0]["title"]
print("Started showcase:", viewer.caption["title"])

# 3. Test Next step
print("Testing skip_showcase_step (Next)...")
viewer.skip_showcase_step()
assert viewer._showcase_idx == 1
assert viewer.director.index == 1
assert viewer.caption["title"] == edu.SHOWCASE[1]["title"]
print("Advanced to:", viewer.caption["title"])

# 4. Test Prev step
print("Testing prev_showcase_step (Back)...")
viewer.prev_showcase_step()
assert viewer._showcase_idx == 0
assert viewer.director.index == 0
assert viewer.caption["title"] == edu.SHOWCASE[0]["title"]
print("Back to:", viewer.caption["title"])

# 5. Test Step Menu jump
print("Testing jump_showcase_step...")
viewer.jump_showcase_step(7)  # Drought
assert viewer._showcase_idx == 7
assert viewer.director.index == 7
assert viewer.caption["title"] == edu.SHOWCASE[7]["title"]
print("Jumped to step 7:", viewer.caption["title"])

# 6. Test pause on caption
print("Testing pause on caption...")
viewer.toggle_pause_on_caption()
assert viewer.director.pause_on_caption == True
viewer.paused = False
viewer.skip_showcase_step()
assert viewer.paused == True, "Expected simulation to be paused when pause_on_caption is True"
print("Pause on caption successfully paused simulation!")

# 7. Test speaker notes toggle
print("Testing speaker notes toggle...")
assert viewer.director.show_speaker_notes == False
viewer.toggle_speaker_notes()
assert viewer.director.show_speaker_notes == True
viewer.toggle_speaker_notes()
assert viewer.director.show_speaker_notes == False
print("Speaker notes toggle works!")

# 8. Test step menu toggle
print("Testing step menu toggle...")
assert viewer.show_step_menu == False
viewer.toggle_step_menu()
assert viewer.show_step_menu == True
viewer.toggle_step_menu()
assert viewer.show_step_menu == False
print("Step menu toggle works!")

# 9. Test keys in _on_key
print("Testing key bindings...")
viewer.toggle_step_menu()
assert viewer.show_step_menu == True
viewer._on_key(pygame.K_3)  # jump to step 3 (0-indexed 2: Herbivores)
assert viewer._showcase_idx == 2
assert viewer.show_step_menu == False
print("Key 3 jumped to step 3!")

viewer._on_key(pygame.K_n)
assert viewer.director.show_speaker_notes == True
viewer._on_key(pygame.K_b)
assert viewer.director.pause_on_caption == False
viewer._on_key(pygame.K_g)
assert viewer.show_step_menu == True
viewer._on_key(pygame.K_ESCAPE)
assert viewer.show_step_menu == False
print("All presenter keys work properly!")

# 10. Test PageDown / PageUp keys
viewer._on_key(pygame.K_PAGEDOWN)
assert viewer._showcase_idx == 3
viewer._on_key(pygame.K_PAGEUP)
assert viewer._showcase_idx == 2
print("PageDown and PageUp keys navigate steps properly!")

# 11. Test Right / Left arrows during showcase
viewer._on_key(pygame.K_RIGHT)
assert viewer._showcase_idx == 3
viewer._on_key(pygame.K_LEFT)
assert viewer._showcase_idx == 2
print("Right and Left keys navigate steps during showcase!")

pygame.quit()
print("\n=== ALL 11 PRESENTER CONTROLS TESTS PASSED SUCCESSFULLY! ===")
