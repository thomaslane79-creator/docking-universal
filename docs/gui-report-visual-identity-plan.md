# GUI and report visual identity plan

Status: planned, 2026-09-20. No production styling or report output is changed
by this document. Source: the user's **Compare Business Plus** conversation
(`6ab00606-f2cc-83ea-8dd6-99e4e9744737`) and the supplied local PNG assets.
This is the visual-identity supplement to the
[GUI implementation roadmap](gui-implementation-roadmap.md).

## Decisions to preserve

- Use a restrained navy/teal identity with flat molecular balls and bonds.
  Keep the Docking Universal wordmark. Do not substitute newly generated art.
- Keep existing report bodies, scientific figures, layouts, and technical
  styling. The approved report change is small attribution, not a redesign.
- Add a quiet report footer combining the small flat mark, actual software
  version, and page number: `Docking Universal · v<version> · Page X of Y`.
  Version examples from the conversation are illustrative, not values to hardcode.
- Add a small software/version attribution outside the data region of exported
  figures. Never watermark the molecule, plot, legend, or interaction diagram.
- Earlier grayscale proposals are superseded by the later request to make the
  flat asset family **except grayscale**. Preserve existing grayscale source
  files, but do not automatically make one the default. The supplied black/white
  single-color variants remain distinct options for contrast or print review.
- Use the detailed protein illustration only where appropriate for optional
  splash/about artwork; it must not consume scientific workspace or report area.

## Retained asset references

The assets are currently outside the repository, under
`/Users/crown2/Documents/ChatGPT/`. Do not relocate or overwrite the originals.
The folder found on 2026-09-20 is `docking_universal_logo_assets_high_res/`.
These paths are implementation inputs, not production runtime dependencies.

| Intended role | Existing asset relative to that directory |
| --- | --- |
| Restrained molecule + wordmark for report/figure attribution | `logo_color.png` (alongside the asset folder) |
| Primary stacked identity | `docking_universal_logo_assets_high_res/01_primary_logo_stacked_8x.png` |
| Standard / compact horizontal identity | `docking_universal_logo_assets_high_res/02_horizontal_logo_standard_8x.png`, `03_horizontal_logo_compact_8x.png` in the same folder |
| Icon-only identity | `docking_universal_logo_assets_high_res/04_icon_only_full_color_8x.png`, `icon_full_color_512px.png`, `icon_full_color_1024px.png` in the same folder |
| Dark-background identity | `05_icon_inverted_dark_8x.png`, `14_reverse_on_dark_stacked_8x.png`, `15_reverse_horizontal_dark_8x.png` in the asset folder |
| App-icon backgrounds | `06_app_icon_white_8x.png` through `09_app_icon_black_8x.png` in the asset folder |
| Single-color alternatives | `16_single_color_white_dark_8x.png` through `19_horizontal_logo_compact_all_black_transparent.png` in the asset folder |
| Favicon | `docking_universal_logo_assets_high_res/docking_universal_favicon.ico` |

Inspected the stacked and compact horizontal images and the separate report
mark. Their dimensions are 3360×3144, 3280×1080, and 2172×724 respectively;
all have alpha channels. Pixel dimensions alone do not establish edge quality
or genuine source detail. Check alpha edges on light and dark backgrounds,
cropping, and small-size readability before choosing production derivatives.
The report mark and newer icon family are not visibly identical shades;
exact shared navy/teal values therefore remain to be selected from the approved
assets, not invented or inferred as already agreed hexadecimal values.

When implementing, inventory and hash chosen originals, record the role of each
derivative, and copy approved runtime sizes into versioned/package resources.
Include those resources in distributions; never load from a developer's absolute
Documents path. Do not ship every oversized PNG merely because it is available.
Montserrat was suggested in the conversation as an approximate typeface, not
identified as the generated lettering's actual font or approved as a new report
body font. Keep existing report typography; verify font licensing/availability
before introducing a new packaged UI font.

## GUI color and layout contract

Introduce centralized semantic theme tokens rather than scattered color strings:
navy for primary actions and selected controls; teal for secondary accents and
active-state differentiation; neutral backgrounds, panels, borders, and text.
The exact assignment is an implementation proposal to preview with the user.
Use white/light gray for the initial light workspace. Inverted assets support a
later dark theme, but their existence does not make a full dark theme a launch gate.

Keep brand colors separate from scientific encodings. Do not recolor pocket
rankings, chain identities, deposited-ligand evidence, PLIP interactions, or
energy/cluster figures just to match the logo. Preserve their legends and the
same identities/colors across report, static figure, and PyMOL scene. Warnings,
errors, and success states require distinct accessible cues plus explanatory text;
teal decoration must not imply scientific approval.

Keep the molecular viewport and decision figures prominent. No large brand
banner, splash artwork, or decorative padding in the review workspace. Preserve
panel-specific A/B/C explanations, fullscreen text, zoom, and Scientific Workflow
Detail. Logs stay secondary; progress, warnings, and actionable evidence stay
visible. Styling must not change selection, approval, calculation, or privacy
semantics. Embedded PyMOL integration and the companion fallback share this
presentation contract without recoloring molecular data.

## Bounded implementation sequence

1. **Asset preparation:** select the existing report mark and GUI/icon variants;
   settle exact palette tokens; inspect transparent edges and true small-size
   readability; retain originals. Review a compact light/dark sample sheet before
   committing packaged derivatives. Do not regenerate the logo as part of this step.
2. **GUI theme slice:** apply tokens to app chrome, focus/selection, and controls
   after the embedded-viewer integration contract is stable. Preview on a standard
   1366×768 display and at Retina/high DPI. Keep the usable viewport large.
3. **Report attribution slice:** implement one shared footer treatment across
   relevant report producers, preserving existing content and layout. Fit within
   the existing footer area where possible; if that is not feasible, review the
   layout consequence rather than silently shrinking figures or body text.
4. **Standalone figure attribution:** stamp once at final export/composition, not
   repeatedly on every A/B/C subpanel. Keep version provenance with cached figures;
   never relabel an old scientific result as generated by a new version. Reuse
   retained calculations; this cosmetic export must not trigger docking again.
5. **README follow-up:** restyle only the discussed workflow graphic,
   `docs/assets/end-to-end-workflows-current-capabilities.png`, preserving its
   workflow content. Recheck its current usage before editing; no blanket restyling
   of molecular images or the rest of the README.

Acceptance: compare representative pocket/protocol and docking PDFs before/after;
check unchanged scientific text, scores, legends, panel alignment, and pagination
except explicitly approved attribution. Render short/long and multipage examples
to check footer collision, clipping, actual version, and Page X of Y. Exercise
CLI and GUI exports, cached images, composite panels, and missing-asset behavior.
Test readable focus/selection/disabled/warning states, keyboard use, standard
resolution, and 1×/2× scaling. Missing branding must not prevent a scientific report
from being generated; use text attribution with a diagnostic instead. No structure
or docked evidence may be uploaded to create or style assets.
