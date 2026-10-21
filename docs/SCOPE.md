# Scope

This project covers **historical places and landmarks**. That boundary is
deliberate, and it is what makes the data trustworthy.

## In scope

- Heritage-listed buildings, monuments, archaeological sites, castles, churches,
  bridges, ruins, memorials, historic districts
- Landmarks with cultural or historical significance
- Natural features that are legally protected or historically documented
- Their coordinates, names, descriptions, photographs, and identifiers

## Out of scope

- **Restaurants, cafés, bars, shops, hotels.** They churn weekly, their data is
  commercial, and Wikimedia does not track them reliably. A dataset that claims
  to cover them would be wrong within a month.
- **Opening hours, phone numbers, prices, ratings, live status.** Not in
  Wikimedia, and Google's versions may not be cached. We do not invent them.
- **Street addresses.** Wikipedia rarely carries them; a guessed address is worse
  than a missing one.
- **Private residences and non-public spaces**, even when historically notable,
  following Overture's public-observability principle.
- **Bulk image rehosting.** We store URLs and licensing metadata, not image bytes.

## Why the line is here

Google's Places API is priced per request and its content may not be stored. The
places that suffer most from that are the ones nobody monetises: a Roman ruin, a
village church, a monument in a country with no advertising market. Those are
precisely the places volunteers have already documented, photographed and
licensed for reuse.

Restaurants are the opposite: high commercial value, constant churn, and no
volunteer pipeline. We are not competing there, and we should not pretend to.

## Changing the scope

Scope changes are governed by [GOVERNANCE.md](GOVERNANCE.md) and require a
maintainer decision recorded in an issue. The default answer is no: breadth is
cheap to claim and expensive to maintain.
