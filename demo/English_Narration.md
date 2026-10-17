# HERE · Indoor visual navigation

PHOTO-BASED INDOOR NAVIGATION

Here combines photo based indoor localization with visual route guidance.

01 / BUILD THE MAP

COLMAP builds a sparse map from a phone video. Reference cameras share one three dimensional coordinate system.

02 / LOCALIZE

Upload a corridor photo. Feature matching and two D to three D registration estimate the camera position and orientation.

03 / READ THE RESULT

These are genuine model coordinates. Metric distances require a measured scale, and are not invented.

04 / PLAN WITH A*

Choose a destination. A star search follows the connected navigation graph. Turn directions come from the camera heading and route vectors.

05 / FOLLOW VISUAL GUIDANCE

A perspective style arrow is drawn on the localization photo. Stored reference images illustrate the upcoming steps.

06 / RE-LOCALIZE

Re-localize to update progress. For this controlled arrival check, we replay a registered waypoint image, then let the program confirm arrival.

REAL APPLICATION / EDITED PHOTO REPLAY

This is a real photo replay, not live augmented reality. On site walking validation is the next step.