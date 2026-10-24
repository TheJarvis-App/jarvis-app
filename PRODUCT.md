# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

(An Electron desktop app for macOS and Windows; its windows are web pages. A phone companion, phone_client.html, is a Home Screen web app.)

## Users

Anyone who talks to their computer instead of clicking through it: the owner speaks or types to Jarvis to play music, open apps, check the weather, ask questions, control Blender and Minecraft, and write code. Coding Mode is for everyone who wants to code with AI, from people who have never opened a terminal to developers; explanations are written so a beginner can follow them, without hiding the details a developer wants.

## Product Purpose

Jarvis is a voice-first desktop assistant ("Hey Jarvis") that does real things on the computer, and says only what really happened. Coding Mode turns one conversation into a complete, working project on disk: the right language and files for the task, checked, explained, and runnable by following its own instructions.

## Positioning

An assistant that acts on this computer and reports truthfully: every "done" is backed by something that really ran (a file written, a check passed, a command that succeeded), and anything not verified is said to be not verified.

## Operating Context

- Used at a desk, often in the evening, by voice or the type bar; the main window is a dark, full-screen-capable dashboard.
- AI is free first: Groq's free plan (rate limits and waits are shown, not hidden); a local AI (Ollama) when chosen. Paid AI is never switched on without the user asking.
- Memory budget: the light (online AI) setup must stay under 2 GB.

## Capabilities and Constraints

- Coding Mode: one chat per project; Jarvis decides the language, framework and files itself (no language or destination pickers); projects are folders under ~/Documents/Jarvis Projects; follow-ups change the same project; backups before edits.
- Generated code is never run without the user's confirmation; tests run in a sandbox on macOS.
- Delivery: VS Code, the folder, Word, Notes, Google Drive, zip.
- Keys and secrets never appear in generated files, logs, or the window.

## Brand Commitments

- Name: Jarvis (renamed from Jervis on 2026-10-06; technical ids keep "jervis").
- Voice: plain, short, honest sentences; never claims success that was not verified.
- Decide details for the user: no pickers or settings questions inside features; one request, sensible automatic choices.

## Product Principles

1. Real over pretend: no fake progress, output, or results.
2. One request is enough: Jarvis makes the technical decisions and says what it chose.
3. Beginner-clear, developer-complete.
4. Free and light by default.
