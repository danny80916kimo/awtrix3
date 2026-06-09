#ifndef ClaydyApp_h
#define ClaydyApp_h

#include <Arduino.h>

enum ClaydyState
{
    CLAUDY_IDLE,
    CLAUDY_THINKING,
    CLAUDY_WORKING,
    CLAUDY_WAITING,
    CLAUDY_ERROR,
    CLAUDY_DONE,
    CLAUDY_OFF
};

// Ghost frame data (8x8, shape-only: 1=on, 0=off)
extern const uint8_t GHOST_THINKING[8][8];
extern const uint8_t GHOST_WORKING1[8][8];
extern const uint8_t GHOST_WORKING2[8][8];
extern const uint8_t GHOST_WAITING[8][8];
extern const uint8_t GHOST_ERROR[8][8];
extern const uint8_t GHOST_DONE[8][8];

class ClaydyApp_
{
private:
    ClaydyApp_() = default;

    ClaydyState state = CLAUDY_OFF;
    int contextPct = 0;
    unsigned long lastUpdateTime = 0;
    unsigned long stateChangeTime = 0;
    bool showingText = false;
    uint8_t workingFrame = 0;
    unsigned long lastFrameToggle = 0;

    void drawGhost(const uint8_t frame[8][8], uint32_t color);
    void drawPercentage(int pct, uint32_t color);
    void drawContextBar(int pct);
    void drawStateText(const char *text, uint32_t color);
    uint32_t getStateColor();
    uint32_t getCtxBrightColor(int pct);
    uint32_t getCtxDimColor(int pct);
    const uint8_t (*getCurrentFrame())[8];

    static const unsigned long IDLE_TIMEOUT = 60000;
    static const unsigned long TEXT_DURATION = 2500;
    static const unsigned long WALK_INTERVAL = 400;

public:
    static ClaydyApp_ &getInstance();
    void updateState(const char *json);
    void tick();
    bool isActive();
};

extern ClaydyApp_ &ClaydyApp;

#endif
