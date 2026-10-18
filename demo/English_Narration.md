# HERE · Photo-first local navigation and cultural discovery

## HERE / PHOTO-FIRST LOCAL NAVIGATION

HERE uses a photo to find your position and guide your next step, without relying on GPS.

## 01 / BUILD THE MAP

COLMAP builds a sparse map from a phone video. Reference cameras share one three dimensional coordinate system.

## 02 / MATCH AND REGISTER

Upload a corridor photo. Feature matching and two D to three D registration estimate the camera position and orientation.

## 03 / READ THE CAMERA POSE

The result includes XYZ and camera orientation, with geometric quality checks. Metric distances require a measured scale.

## 04 / PLAN WITH A*

Choose a destination. A star search follows the connected navigation graph. Turn directions come from the camera heading and route vectors.

## 05 / FOLLOW PHOTO GUIDANCE

Photo guidance compares camera heading with the next route segment. Stored scene images help users recognize upcoming waypoints.

## 06 / RE-LOCALIZE

Re-localize to update progress. For this controlled arrival check, we replay a registered waypoint image, then let the program confirm arrival.

## PLANNED / OPTIONAL NFC SUPPORT

Photo localization comes first. Optional NFC tags could provide an extra check at known map locations.

## FUTURE DIRECTION / AI GLASSES

AI glasses offer a promising next step: hands free navigation, with local stories and cultural check ins along the way.

## FUTURE DIRECTION / TIME LENS

A time lens could reveal how a place has changed, bringing local history into view as people explore.

## HERE / FROM NAVIGATION TO DISCOVERY

Photo first. Find your way, and discover more.