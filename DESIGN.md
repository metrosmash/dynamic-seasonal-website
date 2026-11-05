---
name: Seasonal Website
description: Proof-of-concept demo where an agent redesigns a fictional café site per season.
colors:
  paper: "#f4f1e9"
  paper-white: "#fffdf8"
  ink: "#16130e"
  muted: "#57544a"
  hairline: "#d8d2c2"
  signal: "#a9231b"
  signal-wash: "#f7e4e1"
  ink-wash: "#e9e4d6"
typography:
  headline:
    fontFamily: "Georgia, 'Times New Roman', serif"
    fontSize: "2.25rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.01em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "0.06em"
  body:
    fontFamily: "Georgia, 'Times New Roman', serif"
    fontSize: "1.02rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  panel: "2px"
  control: "3px"
  field: "2px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "20px"
components:
  button-toggle:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 15px"
  button-toggle-hover:
    backgroundColor: "{colors.ink-wash}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 15px"
  button-toggle-active:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    padding: "8px 15px"
  button-danger:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.signal}"
    rounded: "{rounded.control}"
    padding: "8px 15px"
  field-text:
    backgroundColor: "#ffffff"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "8px"
  banner-note:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    padding: "10px 16px"
---

# Design System: Seasonal Website

## Overview

**Creative North Star: "The Morning Edition"**

Each season is an edition going to press, and the shell is the composing room. A
broadsheet lends this working screen exactly four things: a serif story voice against
grotesk rails, a paper ground with black ink and one signal red, dense ruled order, and
a single signature move — the edition line, where status and history are set as press
furniture between rules. Controls stay standard buttons and inputs; the world never
supplies layout or costumes. The seasonal café preview remains agent-generated content
outside this system; the system frames it and narrates its editions.

**Key Characteristics:**

- Broadsheet type, palette, density, and one signature move — never the layout.
- Paper ground, black ink, one signal red for edition markers and danger.
- Serif for story (masthead, about), grotesk for instrument (toggles, rails, readouts).
- The preview frame dominates; chrome above it stays compact and ruled.

## Colors

Paper and ink with a single signal red doing every emphatic job.

### Primary

- **Press Black** (#16130e): Banner fill, masthead rules, panel and frame borders, active
  toggle fill, body ink. The structural color of the page.

### Secondary

- **Signal Red** (#a9231b): Edition number, banner double rule, active-toggle underline,
  reset control, error text. Reserved for edition markers and danger; never decoration.

### Neutral

- **Newsprint** (#f4f1e9): Page ground.
- **Paper White** (#fffdf8): Panels and button faces.
- **Muted Column** (#57544a): History path and secondary readouts.
- **Column Rule** (#d8d2c2): Interior dividers.
- **Ink Wash** (#e9e4d6): Toggle hover fill.
- **Signal Wash** (#f7e4e1): Reset hover fill.

### Named Rules

**The One Red Rule.** Signal Red marks editions and danger only. Seasonal color lives
exclusively inside the café preview, never in the shell.

## Typography

**Display Font:** none; the masthead is a headline, not display type.
**Body Font:** Georgia, "Times New Roman", serif (story text).
**Label/Mono Font:** system grotesk stack (instrument text).

**Character:** The page speaks in two registered voices: serif tells the story, grotesk
works the instrument. Neither borrows the other's job.

### Hierarchy

- **Headline** (bold serif, 2.25rem, 1.1): Masthead title; about opens at 1.6rem serif.
- **Title** (bold grotesk, 1.05rem, uppercase, 0.06em tracking): Panel and section heads.
- **Body** (regular serif, 1.02rem, 1.55, 65–70ch): About copy and subtitle.
- **Label** (regular grotesk, 0.9rem): History path, banner note (0.92rem), readouts.

### Named Rules

**The Two Voices Rule.** Serif narrates, grotesk operates. Controls, status, and labels
never set in serif; story copy never sets in grotesk.

## Layout

A single centered column (60rem max): sticky banner rule, serif masthead with a bottom
rule, control panel, dominant preview frame (70vh, 75vh on phones), about panel. Panel
heads are uppercase grotesk; more space sits above headings than below. Below 36rem the
gutters shrink to 0.75rem and panels tighten to 1rem. Spacing rhythm is 4/8/16/20px.

## Elevation & Depth

Flat newsprint. No shadows anywhere; separation comes from 1px ink rules, the 3px double
rule accent, and tonal steps between Newsprint, Paper White, and washes. Hover and
active are instant fill swaps with one quiet 120ms ease-out on button faces.

### Named Rules

**The Ink-On-Paper Rule.** Depth is a rule or a tone step, never a shadow or lift.

## Shapes

Sharp press corners: 2px on panels, frame, and inputs; 3px on buttons. The double rule
(3px) is the only ornamental geometry, used on the banner edge and the edition block.

## Components

### Buttons

Standard grotesk buttons in press livery.

- **Shape:** Near-sharp corners (3px radius).
- **Primary (toggle):** Ink text and 1px border on Paper White; 8px 15px padding.
- **Hover / Focus:** Ink Wash fill over 120ms; Signal Red 2px focus outline offset 2px.
- **Active season:** Press Black fill, Newsprint text, inset 3px Signal Red underline.
- **Danger (Reset):** Same construction in Signal Red with a Signal Wash hover.
- **Disabled:** 55% opacity; the status line narrates the wait.

### Inputs / Fields

- **Style:** White field, 1px ink stroke, 2px radius, 8px padding, flexible width.
- **Focus:** Signal Red outline (no browser-default ring).
- **Error / Disabled:** Disabled dims with the control group; no error state exists.

### Cards / Containers

- **Corner Style:** 2px radius.
- **Background:** Paper White.
- **Shadow Strategy:** None (see Elevation & Depth).
- **Border:** 1px Press Black.
- **Internal Padding:** 1.25rem 1.5rem (1rem on phones).

### Navigation

No site navigation exists; the masthead holds only the title and subtitle. In-preview
café navigation belongs to the generated content, not this system.

### Edition Line (signature component)

Status and history set as press furniture: bold grotesk status with the edition number
in Signal Red, history path in Muted Column below, the block ruled with a 3px double
rule above and a 1px rule below. Errors reuse the block in Signal Red, naming the
problem and the recovery.

### Banner Note (signature component)

Full-bleed sticky strip, Press Black fill with Newsprint 0.92rem text and a double
Signal Red baseline. It carries the proof-of-concept notice and survives every seasonal
state by living outside the redesigned files.

### Preview Frame (signature component)

The 70vh (75vh on phones) iframe in a 1px Press Black border at 2px radius. The visual
anchor of the page: compact ruled chrome above, all expression inside.

## Do's and Don'ts

### Do:

- **Do** keep the shell to paper, ink, and Signal Red.
- **Do** set new instrument text in grotesk and new story text in serif.
- **Do** rule state changes: edition block, section heads, and dividers carry rules.
- **Do** keep the banner visible and sticky in every state.

### Don't:

- **Don't** add shadows, gradients, or animation beyond the single button ease.
- **Don't** set controls in serif or story copy in grotesk; the voices don't cross.
- **Don't** put seasonal color, emoji, or decoration in the chrome; expression belongs inside the preview.
- **Don't** invent testimonials, metrics, or brand claims anywhere in the demo copy.
