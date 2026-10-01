#pragma once

/* Glitch filter: holds back readings that jump away from the accepted weight until the new value
 * has been confirmed by several readings in a row. */
void glitch_filter_reset(float kg);
float glitch_filter(float kg);

/* Moving average over the last AVG_N filtered readings, for a steady display. */
float display_average(float kg);
