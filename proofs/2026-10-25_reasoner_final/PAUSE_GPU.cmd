@echo off
rem Owner pause: the reasoner trainer saves a checkpoint, frees the GPU and exits within ~1 training step (up to ~3 min).
echo paused %DATE% %TIME% > "%~dp0PAUSE_GPU"
echo Reasoner training will checkpoint and stop within a few minutes. The agent resumes it.
