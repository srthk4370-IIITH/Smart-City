# Agentic Edge AI for Smart Cities

### Team Details
- Team Number: esw-m26-14
- Team Name: NASA
- Course/Module: ESW-M26

---

# Repository Instructions

This repository contains the codebase, resources, and demonstration materials for our Agentic Edge AI for Smart Cities project.

## 1. Repository Structure

- `Code/` - Contains all project source code, scripts, configs, and the core Edge Agent implementation.
- `Resources/` - Contains supporting material such as references, documents, and resource documentation.
- `Demos/` - Contains demonstration videos, images, screenshots, or a README file with public links to the media.
- `Presentation/` - Contains the final presentation in PDF format used for evaluation.

## 2. Project Overview

We are building a multi-agent system deployed on the Qualcomm AI Hub (QIDK) edge device to monitor and respond to smart city scenarios. This includes domains like Energy, Water, Occupancy, and Weather. The system uses a 4-step pipeline to orchestrate lightweight, on-device anomaly detection and action-taking via Llama 3.2 3B Instruct.

## 3. Documentation & Execution

A clear, step-by-step guide for setup, execution, model downloading, and deployment is available in:
- `run.md` - Complete setup, training, and execution steps.
- `deploy.md` - Advanced deployment instructions for QIDK.

## 4. Reproducibility

The project relies on:
- Python 3.10+
- ADB (Android Debug Bridge) for device communication.
- Qualcomm AI Hub SDK for model conversion and deployment.

See `run.md` for specific environment setup details.

## 5. AI Usage and Transparency

- Generative AI was used for developing documentation, deployment scripts, and configuring the CI/CD environment.
- No AI was used to generate the core models, but Llama 3.2 is utilized on the edge as the orchestration model.
