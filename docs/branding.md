# PARSE by ShipHero

**Policies Analyzed into Rules, Standards & Exceptions**

Tagline: **From retailer requirements to operational rules.**

## Identity

PARSE is the product name; “by ShipHero” is the parent endorsement. The coral geometric P shares the rounded hexagonal construction of ShipHero's S without replacing it. The official ShipHero logo remains intact in the endorsement. This is a proposed product identity, not a replacement corporate brand standard.

The app uses `ParseBrand.tsx` for the compact lockup and the standalone mark as its favicon. Brand reference material and downloadable assets stay in the repository; there is no dedicated brand page in the app. The original Retail Solutions footer wording is preserved. The Git repository and project directory are named `parse`. Existing infrastructure names remain `routing-guides` to preserve Docker volumes and local data.

## Assets

- `frontend/src/assets/brand/parse-mark.png`: generated transparent PNG; original resolution retained.
- `frontend/src/assets/brand/parse-logo.svg`: portable light-background lockup with embedded PNG mark and official ShipHero logo; this is not an all-vector master. Wordmark uses Arial/Helvetica/sans-serif.
- `frontend/src/assets/brand/shiphero-logo.svg`: unchanged official logo downloaded from the public website for the endorsement.

Keep clear space around the mark. Do not stretch, add shadows or add detail. Use the mark alone for small icons. Use the full charcoal lockup on light backgrounds; the coral standalone mark can be used on charcoal. UI typography remains the existing system sans-serif stack, with no external font dependency.

## Palette

| Token | Color | Use |
| --- | --- | --- |
| ShipHero coral | `#F05D5A` | Mark and restrained identity accents |
| ShipHero charcoal | `#242E3A` | Wordmark, headings, primary actions |
| ShipHero blue | `#4287FF` | Brand graphics and focus accents |
| Interface blue | `#225BC4` | Darker derivative for readable links and selected controls |
| Canvas | `#F6F8FB` | App background |
| White | `#FFFFFF` | Tables, forms and panels |

The PNG's generated colors may vary slightly from the specified coral. UI colors use the exact tokens. Approval, warning and error colors keep their semantic meaning. Coral is not used for normal action text on white.

## References

Reference checked October 20, 2026: [ShipHero website](https://www.shiphero.com/). The [official primary SVG](https://cdn.prod.website-files.com/6915f01ece943af094239ff7/6980e5ceea22740af04071d3_SH-color-full-tm.svg) defines coral `#f05d5a` and charcoal `#242e3a`. The public website stylesheet defines blue `#4287ff` (and a slightly different website red `#ef5252`); the logo colors are the identity reference here.

## Generation record

The standalone P mark was created with the built-in image-generation tool, using a rendered reference of the official ShipHero logo. No API-key CLI fallback was used. Original generated file: `exec-46c25f49-f947-4c56-90f5-a0182b0f6ad8.png`.

Prompt:

> Use case: logo-brand. Create a single production-ready flat logo symbol for PARSE, an enterprise retailer compliance software by ShipHero. The supplied image is a STYLE REFERENCE ONLY: ShipHero's existing coral hexagonal S symbol and charcoal wordmark. Design a distinct PARSE symbol with the same confident geometric family: a chunky, clearly readable capital P formed from coral-red #F05D5A geometric bands, with a subtle folded-document or structured-rules negative-space cut. Compact, balanced, nearly square silhouette, gently softened corners, strong legibility at 32px. Prefer an angular hexagonal outer construction echoing the parent brand, with unmistakable P counter and stem; do not copy the S. One solid coral color only. Transparent background. Symbol only, no lettering or wordmark outside the symbol, no captions, no mockup, no shadows, no gradients, no 3D, no tiny detail. Center the symbol and let it occupy 88 percent of the canvas with a small even transparent margin. This is the actual app icon, not a brand presentation sheet.
