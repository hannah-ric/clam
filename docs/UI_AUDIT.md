# FRONT-END INTERFACE AUDIT
## Resort Climate Risk Explorer, app v2.3.0 (deployable v210, assembled from app/src/)

Prepared 8 July 2026. Method: full read of README.md, MASTER_PLAN.md, docs/, every
module in app/src/, both test harnesses (tests/test_frontend.py, tests/test_app_parity.py),
plus a rendered walkthrough of the deployable in headless Chromium at 1440x900 and
900x700, online and offline, across every tab and both view modes.

This audit changes nothing. The change plan at the end maps each accepted issue to a
small commit. Numeric parity is a hard constraint throughout: no fix below touches a
computed value, the export schemas, or the localStorage keys.

=============================================================================
SECTION 1: WHAT ALREADY WORKS WELL
=============================================================================

Worth stating first, because the overhaul must not lose these:

- The trust surface is genuinely good. Per-peril chips, per-site trust strips,
  dashed degraded markers, the n/6 model-basis badge, gray "awaits data" states,
  and honest zero notes ("TC rainfall has no interim model by design") are all
  present and tested. Nothing overclaims.
- Score tracing ("Why these numbers") walks every figure to its grid cell or
  named interim model with the factors applied. A test pins the wind factor
  trail's product to vulnOf.
- The INFO popover corpus is extensive and plainly written.
- The executive home is a strong one-minute view: headline, three tiles, ranked
  plan with dollars and act-by deadlines, all reading from the same pinned engine.
- Empty states on Summary and Overview offer one obvious action (Load sample).
- The decision view leads with physical units and re-sorts on click.
- Degradation is graceful: offline, the map area collapses to a clear message and
  every analysis still works.

=============================================================================
SECTION 2: WALKTHROUGH BY AREA
=============================================================================

Each area: what works, what confuses a first-time user, what looks unpolished,
what is not accessible, and what the obvious next step is not.

-----------------------------------------------------------------------------
2.1 Method and data intake
-----------------------------------------------------------------------------
Works: two clear drop zones with schema hints; multi-file drops merge correctly;
the pack panel appears beside the live model; the plain-language glossary is a
real asset.

Confuses: the tab renders as one unbroken wall of dense panels. The hazard drop
zone sits ABOVE the sites drop zone, but a new user's first step is sites, not
hazard. Nothing states the order of operations (1 load sites, 2 load the grid,
3 optionally the pack and backtest). The glossary, the model definition, and the
Power BI wiring notes all carry equal visual weight, so the two actions that
matter drown.

Unpolished: the "Model definition" and note blocks run to thousands of words at
uniform size; the drop zones look identical whether empty or loaded.

Accessibility: drop zones are click-targets but carry no keyboard hint; they work
via the hidden file input, which is fine, but the affordance is invisible.

Missing next step: after a sites CSV loads there is no pointer back to Summary;
after a grid loads there is no "now read the Summary" cue beyond a toast.

-----------------------------------------------------------------------------
2.2 Scorecards and score tracing
-----------------------------------------------------------------------------
Works: the scorecard is the best single surface in the product: KPIs, cost split,
trajectory, RP table, best actions, named-insured breakout, trust strip, trace,
and a narrative, all in one overlay. Trace rows collapse by default (good
progressive disclosure).

Confuses: the overlay opens with no focus management, so keyboard users stay
behind it; Escape works but is undiscoverable. The "Edit site" and "Close"
buttons sit far from the content a keyboard user is in.

Unpolished: cards inside the overlay use a smaller ad hoc font size (19px) than
the main KPI cards (26px); the trace summary line mixes bullet separators and
parentheses inconsistently.

Accessibility: the modal has no role="dialog"/aria-modal, no focus trap, no
focus restore on close.

-----------------------------------------------------------------------------
2.3 Scenario timeline (Present to 2080)
-----------------------------------------------------------------------------
Works: one shared engine drives the top-bar selects, the Summary scrubber, and
the executive timeline pill; they cannot drift. Play animates the walk.

Confuses: the same control exists in three shapes (two selects, a segmented
scrubber, a pill) with three visual styles. The horizon select keeps showing a
stale year (for example 2030) grayed out while "Present day" is selected, which
reads as a live setting.

Unpolished: the scrubber panel is a bare white strip; the Play button gives no
progress indication.

Accessibility: scrubber steps are buttons (good) but the group announces nothing
about the current step; Play state lives only in its label.

-----------------------------------------------------------------------------
2.4 Map and brand filter
-----------------------------------------------------------------------------
Works: markers encode value (size), band (fill), and model basis (ring + n/6
badge); the legend explains all three; popups deep-link to scorecards; brand
filter and colour lenses are display-only by design.

Confuses: OFFLINE, executive mode floats its panels over a large blank void;
the colour bar overlaps the "Map is unavailable" sentence; the product looks
broken exactly in the environment (locked-down laptop) it was designed for.
Leaflet JS/CSS load from unpkg and the fonts from Google Fonts, so the
"self-contained file" promise is only half true today: the logic is offline,
the look is not.

Unpolished: with fonts blocked, every heading falls back to the default browser
serif (Times), which reads as unstyled; the brand filter lives in the top bar in
analyst mode but resets every session (deliberate, but it contradicts "persists
like every other view preference").

Accessibility: the n/6 trust badge tooltip text is 9.5px; marker rings alone
would fail colour-blind users but the permanent text badge saves it (good).

-----------------------------------------------------------------------------
2.5 Financial layer
-----------------------------------------------------------------------------
Works: KPI cards with uncertainty ranges; the tail always states its basis
(joint event tail vs blend approximation); assumptions are visible sliders with
per-brand overrides; disclosure table matches TCFD/ISSB shape.

Confuses: five sliders plus a brand-override table plus a correlation slider sit
in one "Assumptions" panel with no grouping between revenue assumptions and
portfolio assumptions. Slider values echo in mono text but the effect (which
numbers move) is invisible until you look elsewhere.

Unpolished: native range inputs render in default browser blue, clashing with
the palette everywhere they appear (Financial, Adaptation, measure cards).

Accessibility: sliders have labels (good) but no visible min/max scale.

-----------------------------------------------------------------------------
2.6 Adaptation and capital plan
-----------------------------------------------------------------------------
Works: the appraisal settings recompute live; measure cards carry scope counts,
cost, averted, benefit; the queue enforces defer-not-drop and states the joint
roll-up; the pack plan renders beside the live queue as canonical.

Confuses: this tab is the longest page in the product (measure library, cost
curve, waterfall, layering, retention, act-first table, action queue) with no
in-page navigation and no summary of what the tab answers. A first-time user
cannot tell which panel is the decision and which is supporting detail.

Unpolished: unchecked measures dim via opacity on the whole card, which reads
as disabled rather than "not selected"; the BCR figure sits inside the card
header at a different alignment from the cost/averted stats.

Accessibility: the measure checkboxes are real inputs (good); the queue table
has no caption; funded/unfunded is colour+word (good).

-----------------------------------------------------------------------------
2.7 Insurance layering
-----------------------------------------------------------------------------
Works: attachment/exhaustion/loading with live layer stats; the quote verdict
is honest about what a technical premium is; the retention sweep answers a real
renewal question; the broker pack export is one click.

Confuses: "Priced on: live correlation blend (direct + BI): a co-occurrence
approximation, not the joint event tail" is exact and honest but long; the
key-value stack it opens is 8 rows of mono text before the chart.

Unpolished: the layer chart's shaded bands (retain/transfer/tail) explain
themselves only in a caption line below the axis.

-----------------------------------------------------------------------------
2.8 Uncertainty bands
-----------------------------------------------------------------------------
Works: the tornado is honest (one-at-a-time screening, labeled); ranges appear
on the Summary KPI and the finance KPIs; the pack's p5..p95 shows when loaded.

Confuses: the tornado's axis text at 9.5-10.5px is hard to read; the "largest
driver" insight is buried in a kv row rather than stated as a sentence.

Unpolished: hidden entirely in Simple view (correct), but nothing in Simple
view says specialist panels are hidden.

-----------------------------------------------------------------------------
2.9 Board brief
-----------------------------------------------------------------------------
Works: one click, print CSS, states its data basis and assumptions, includes the
pack plan when loaded, zero dependencies.

Confuses: nothing tells the user to pick "Save as PDF" until after the dialog
opens (the INFO entry says it, the button does not).

Unpolished: brief tables have no column headers; the kicker line duplicates the
top bar brand.

-----------------------------------------------------------------------------
2.10 Cross-cutting: layout, controls, theming
-----------------------------------------------------------------------------
- The analyst top bar carries the search, the badge, six selects, an info
  button, four buttons, a mode switch, and the export menu. At 1440px it wraps
  into two dense rows; the tiny 9px uppercase labels (PERIL, PATHWAY...) render
  at roughly 2.6:1 contrast on the dark header. This is the single most
  unpolished surface in the product.
- There is no dark mode, no display-density option, and no way to choose which
  panels show beyond the all-or-nothing Simple view.
- The palette is applied as ~110 scattered hex literals across the CSS and the
  chart-generating JS. Restyling today means editing every chart function.
- Type: three families (Fraunces, Inter, IBM Plex Mono) from a CDN; offline the
  serif falls back to Times and the UI to system sans, so two users can see two
  different products.
- Tables: only the decision view shows sort direction; the Sites table sorts
  invisibly. The ratings pill row overflows its cell at 1440px and clips.
- The toast overlaps the executive timeline pill at the bottom centre and is
  not announced to screen readers.
- Tab navigation: correct ARIA roles but no arrow-key behaviour, no keyboard
  shortcut hints anywhere.

=============================================================================
SECTION 3: RANKED ISSUES
=============================================================================

Severity: S1 breaks trust or blocks a class of users; S2 materially hurts
comprehension or polish; S3 cosmetic or minor friction.
Effort: E1 hours; E2 a day; E3 multiple days.

| #  | Issue                                                                 | Sev | Eff |
|----|-----------------------------------------------------------------------|-----|-----|
| 1  | Fonts load from Google CDN; offline users get Times fallback          | S1  | E1  |
| 2  | No design-token layer; palette/type scattered across ~110 hex literals| S1  | E2  |
| 3  | Analyst top bar overload; 9px labels at ~2.6:1 contrast               | S1  | E2  |
| 4  | Executive mode offline: floating panels over a blank void             | S1  | E1  |
| 5  | No dark mode, no density control, no panel visibility control         | S2  | E3  |
| 6  | Modal a11y: no dialog role, focus trap, or focus restore              | S2  | E1  |
| 7  | Toast not announced (aria-live) and overlaps exec timeline            | S2  | E1  |
| 8  | Method tab: no guided order; hazard zone above sites zone             | S2  | E1  |
| 9  | Empty states missing on Sites/Adaptation/Scenarios/Finance tabs       | S2  | E1  |
| 10 | Muted text (#7A8893) at 4.0:1 on the page background                  | S2  | E1  |
| 11 | Brand filter resets every session                                     | S2  | E1  |
| 12 | Sites table: no sort indicator; ratings pills clip at 1440px          | S2  | E1  |
| 13 | Tabs: no arrow-key navigation                                         | S2  | E1  |
| 14 | Adaptation tab has no in-page orientation                             | S2  | E1  |
| 15 | Horizon select shows a stale year while disabled                      | S3  | E1  |
| 16 | Range inputs render default browser blue                              | S3  | E1  |
| 17 | Chart/axis text at 9.5-10.5px                                         | S3  | E2  |
| 18 | Scrubber/timeline/selects: three styles for one control               | S3  | E2  |
| 19 | Footer version line is an unreadable mono blob                        | S3  | E1  |
| 20 | Main column capped at 1220px; wasted space on large displays          | S3  | E1  |
| 21 | Leaflet JS/CSS from unpkg (works offline only as degraded no-map)     | S2  | E2* |

=============================================================================
SECTION 4: FLAGGED FOR SIGN-OFF (fix could touch numbers or behaviour contracts)
=============================================================================

Set aside per the ground rules; nothing below is changed in this overhaul.

F1. Embedding Leaflet (~180 KB) into the single file (#21). It removes the CDN
    dependency but cannot bring map TILES offline; the map needs the network
    either way. This overhaul instead styles the offline no-map state properly
    and leaves Leaflet loading as is. Say the word if you want Leaflet embedded.

F2. A return-period lens (10..500) on the decision view and Sites table. The
    values at other return periods are already computed and shown per site, but
    surfacing a different column default changes which numbers a reader quotes.
    Not built; flagged as a candidate configurable.

F3. The horizon select applying to "Present day" (it is ignored today). Making
    it always-active would change which scenario key some views read. Left as
    is; the fix shipped is display-only (clearer disabled presentation).

F4. Number formatting (fmt$ rounding, "$1.24M" style) is left byte-identical
    everywhere; several exports and tests pin derived strings.

=============================================================================
SECTION 5: CHANGE PLAN (accepted scope, in commit order)
=============================================================================

Each commit reassembles the deployable and passes bash tests/run_all.sh.

C1. Token layer + offline typography (#1, #2, #10, #16, #19).
    One named :root token set: TNL palette (nero, dune, vista, sand, sky),
    semantic surfaces/ink/lines, type scale, spacing scale, radii, shadows.
    Remove the Google Fonts links; local-first stacks (Fraunces/Archivo if
    installed, else system). Styled range inputs. Contrast floor at WCAG AA.

C2. Dark mode + chart theming (#5 part 1, #17).
    html[data-theme] token overrides; chart chrome colours in the generated
    SVGs move from hex literals to var() styles so both themes render without
    re-render; band and peril colours stay identical in both themes (they are
    data encodings, not chrome). Theme persists via the existing ui state.

C3. Display options + persistence (#5 part 2, #11).
    A Display menu in the top bar: theme, density (comfortable/compact),
    detail level (the existing Simple view, renamed), and Summary panel
    visibility. All persisted in ui with defensive merge. Brand filter
    persists in ui.views.

C4. Top bar and navigation (#3, #13, #15, #18).
    Slim the dark header to identity, search, trust badge, mode switch,
    Display, Export. Move the five view selects to a light "view bar" row
    that sits with the tabs in analyst mode. Arrow-key tab navigation.
    Disabled horizon reads as blank. Legible labels.

C5. States and guidance (#4, #7, #8, #9, #14).
    Offline executive backdrop; aria-live toast repositioned; Method tab
    reordered (sites first) with a numbered 1-2-3 path; consistent empty
    states on every tab with one primary action; a one-line orientation on
    the Adaptation tab.

C6. A11y and responsive polish (#6, #12, #20).
    Dialog semantics, focus trap and restore on the three modals; sort
    indicators on the Sites table; ratings row wrap fix; wide-screen layout
    (main up to 1440px); skip-to-content link.

Out of scope, unchanged: every computed number, the Power BI export, both new
CSV artifacts, localStorage keys, the INFO corpus text pinned by tests, trust
semantics, and the patch lineage.
