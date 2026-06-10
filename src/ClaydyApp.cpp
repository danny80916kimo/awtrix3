#include "ClaydyApp.h"
#include "DisplayManager.h"
#include "PeripheryManager.h"
#include "Globals.h"
#include <ArduinoJson.h>

// ── Ghost frame data (8x8, shape-only: 1=on, 0=off) ──

const uint8_t GHOST_ERROR[8][8] = {
    {0,0,0,0,0,0,0,0},
    {0,1,1,1,1,1,1,0},
    {0,1,0,1,1,0,1,0},
    {1,1,0,1,1,0,1,1},
    {0,1,1,1,1,1,1,0},
    {0,0,1,1,1,1,0,0},
    {0,0,1,0,0,1,0,0},
    {0,0,0,0,0,0,0,0},
};

const uint8_t GHOST_DONE[8][8] = {
    {0,0,0,0,0,0,0,0},
    {0,1,1,1,1,1,1,0},
    {0,1,0,1,1,0,1,0},
    {0,1,0,1,1,0,1,0},
    {0,1,1,1,1,1,1,0},
    {1,1,1,1,1,1,1,1},
    {0,1,1,1,1,1,1,0},
    {0,0,1,0,0,1,0,0},
};

const uint8_t GHOST_THINKING[8][8] = {
    {0,0,0,0,0,0,0,0},
    {0,1,1,1,1,1,1,0},
    {0,1,0,1,1,0,1,0},
    {0,1,0,1,1,0,1,0},
    {0,1,1,1,1,1,1,1},
    {1,1,1,1,1,1,1,0},
    {0,1,1,1,1,1,1,0},
    {0,0,1,0,0,1,0,0},
};

const uint8_t GHOST_WORKING1[8][8] = {
    {0,1,1,1,1,1,1,0},
    {0,1,0,1,1,1,1,0},
    {0,1,0,1,1,0,1,0},
    {1,1,1,1,1,1,1,1},
    {0,1,1,1,1,1,1,0},
    {0,0,1,0,0,1,0,0},
    {0,0,0,0,0,1,0,0},
    {0,0,0,0,0,0,0,0},
};

const uint8_t GHOST_WORKING2[8][8] = {
    {0,1,1,1,1,1,1,0},
    {0,1,1,1,1,0,1,0},
    {0,1,0,1,1,0,1,0},
    {1,1,1,1,1,1,1,1},
    {0,1,1,1,1,1,1,0},
    {0,0,1,0,0,1,0,0},
    {0,0,1,0,0,0,0,0},
    {0,0,0,0,0,0,0,0},
};

const uint8_t GHOST_WAITING[8][8] = {
    {0,0,0,0,0,0,0,0},
    {0,1,1,1,1,1,1,0},
    {0,1,1,1,1,1,1,0},
    {0,1,0,1,1,0,1,0},
    {1,1,1,1,1,1,1,1},
    {0,1,1,1,1,1,1,0},
    {0,0,1,0,0,1,0,0},
    {0,0,0,0,0,0,0,0},
};

// ── Tiny 4x3 font for state text ──
// Each character is 3 pixels wide, 4 pixels tall (stored as 4 rows of 3 bits)
// Characters: A D E H I K N O R T W

static const uint8_t TINY_A[] = {0b010, 0b101, 0b111, 0b101};
static const uint8_t TINY_D[] = {0b110, 0b101, 0b101, 0b110};
static const uint8_t TINY_E[] = {0b111, 0b110, 0b100, 0b111};
static const uint8_t TINY_H[] = {0b101, 0b101, 0b111, 0b101};
static const uint8_t TINY_I[] = {0b111, 0b010, 0b010, 0b111};
static const uint8_t TINY_K[] = {0b101, 0b110, 0b110, 0b101};
static const uint8_t TINY_N[] = {0b101, 0b111, 0b111, 0b101};
static const uint8_t TINY_O[] = {0b111, 0b101, 0b101, 0b111};
static const uint8_t TINY_R[] = {0b111, 0b101, 0b110, 0b101};
static const uint8_t TINY_T[] = {0b111, 0b010, 0b010, 0b010};
static const uint8_t TINY_W[] = {0b101, 0b101, 0b111, 0b010};

static const uint8_t *getTinyChar(char c)
{
    switch (c)
    {
    case 'A': return TINY_A;
    case 'D': return TINY_D;
    case 'E': return TINY_E;
    case 'H': return TINY_H;
    case 'I': return TINY_I;
    case 'K': return TINY_K;
    case 'N': return TINY_N;
    case 'O': return TINY_O;
    case 'R': return TINY_R;
    case 'T': return TINY_T;
    case 'W': return TINY_W;
    default:  return nullptr;
    }
}

// ── Tiny 5x3 digit font for percentage display ──
// Each digit is 3 pixels wide, 5 pixels tall

static const uint8_t DIGIT_0[] = {0b111, 0b101, 0b101, 0b101, 0b111};
static const uint8_t DIGIT_1[] = {0b010, 0b110, 0b010, 0b010, 0b111};
static const uint8_t DIGIT_2[] = {0b111, 0b001, 0b111, 0b100, 0b111};
static const uint8_t DIGIT_3[] = {0b111, 0b001, 0b111, 0b001, 0b111};
static const uint8_t DIGIT_4[] = {0b101, 0b101, 0b111, 0b001, 0b001};
static const uint8_t DIGIT_5[] = {0b111, 0b100, 0b111, 0b001, 0b111};
static const uint8_t DIGIT_6[] = {0b111, 0b100, 0b111, 0b101, 0b111};
static const uint8_t DIGIT_7[] = {0b111, 0b001, 0b001, 0b001, 0b001};
static const uint8_t DIGIT_8[] = {0b111, 0b101, 0b111, 0b101, 0b111};
static const uint8_t DIGIT_9[] = {0b111, 0b101, 0b111, 0b001, 0b111};
// % sign: 3 wide x 5 tall
static const uint8_t DIGIT_PCT[] = {0b101, 0b001, 0b010, 0b100, 0b101};

static const uint8_t *getDigitFont(char c)
{
    switch (c)
    {
    case '0': return DIGIT_0;
    case '1': return DIGIT_1;
    case '2': return DIGIT_2;
    case '3': return DIGIT_3;
    case '4': return DIGIT_4;
    case '5': return DIGIT_5;
    case '6': return DIGIT_6;
    case '7': return DIGIT_7;
    case '8': return DIGIT_8;
    case '9': return DIGIT_9;
    case '%': return DIGIT_PCT;
    default:  return nullptr;
    }
}

// ── Singleton ──

ClaydyApp_ &ClaydyApp_::getInstance()
{
    static ClaydyApp_ instance;
    return instance;
}

ClaydyApp_ &ClaydyApp = ClaydyApp_::getInstance();

// ── Color helpers ──

uint32_t ClaydyApp_::getStateColor()
{
    switch (state)
    {
    case CLAUDY_THINKING: return 0x00BFFF;
    case CLAUDY_WORKING:  return 0xFFD700;
    case CLAUDY_WAITING:  return 0x00CED1;
    case CLAUDY_ERROR:    return 0xFF4444;
    case CLAUDY_DONE:     return 0x44FF44;
    case CLAUDY_IDLE:
    default:              return 0x888888;
    }
}

uint32_t ClaydyApp_::getCtxBrightColor(int pct)
{
    if (pct < 75) return 0x00CED1;
    if (pct < 90) return 0xFFA500;
    return 0xFF4444;
}

uint32_t ClaydyApp_::getCtxDimColor(int pct)
{
    if (pct < 75) return 0x004F50;
    if (pct < 90) return 0x553800;
    return 0x551111;
}

// ── Drawing functions ──

void ClaydyApp_::drawGhost(const uint8_t frame[8][8], uint32_t color)
{
    for (int r = 0; r < 8; r++)
    {
        for (int c = 0; c < 8; c++)
        {
            if (frame[r][c])
            {
                DisplayManager.drawPixel(c, r, color);
            }
        }
    }
}

void ClaydyApp_::drawStateText(const char *text, uint32_t color)
{
    int x = 10;
    int y = 2;
    for (int i = 0; text[i] != '\0'; i++)
    {
        const uint8_t *glyph = getTinyChar(text[i]);
        if (!glyph) continue;
        for (int row = 0; row < 4; row++)
        {
            for (int col = 0; col < 3; col++)
            {
                if (glyph[row] & (0b100 >> col))
                {
                    DisplayManager.drawPixel(x + col, y + row, color);
                }
            }
        }
        x += 4; // 3px char + 1px spacing
    }
}

void ClaydyApp_::drawPercentage(int pct, uint32_t color)
{
    // Build the string: digits + '%'
    char buf[8];
    snprintf(buf, sizeof(buf), "%d%%", pct);

    // Calculate total width: each char is 3px wide + 1px spacing, minus trailing space
    int len = strlen(buf);
    int totalWidth = len * 4 - 1; // 3px per char + 1px gap, no trailing gap

    // Right-align ending at column 30 (so rightmost pixel is col 30)
    int x = 31 - totalWidth;
    int y = 1;

    for (int i = 0; buf[i] != '\0'; i++)
    {
        const uint8_t *glyph = getDigitFont(buf[i]);
        if (!glyph) continue;
        for (int row = 0; row < 5; row++)
        {
            for (int col = 0; col < 3; col++)
            {
                if (glyph[row] & (0b100 >> col))
                {
                    DisplayManager.drawPixel(x + col, y + row, color);
                }
            }
        }
        x += 4;
    }
}

void ClaydyApp_::drawContextBar(int pct)
{
    // Row 7, columns 10..30 (21 pixels wide)
    int barWidth = 21;
    int filled = (pct * barWidth) / 100;
    uint32_t bright = getCtxBrightColor(pct);
    uint32_t dim = getCtxDimColor(pct);

    for (int i = 0; i < barWidth; i++)
    {
        uint32_t c = (i < filled) ? bright : dim;
        DisplayManager.drawPixel(10 + i, 7, c);
    }
}

const uint8_t (*ClaydyApp_::getCurrentFrame())[8]
{
    switch (state)
    {
    case CLAUDY_THINKING: return GHOST_THINKING;
    case CLAUDY_WORKING:  return (workingFrame == 0) ? GHOST_WORKING1 : GHOST_WORKING2;
    case CLAUDY_WAITING:  return GHOST_WAITING;
    case CLAUDY_ERROR:    return GHOST_ERROR;
    case CLAUDY_DONE:     return GHOST_DONE;
    case CLAUDY_IDLE:
    default:              return GHOST_WAITING;
    }
}

// ── State management ──

void ClaydyApp_::updateState(const char *json)
{
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, json);
    if (err) return;

    const char *stateStr = doc["state"] | "";
    int pct = doc["pct"] | contextPct;

    ClaydyState newState = state;

    if (strcmp(stateStr, "thinking") == 0)      newState = CLAUDY_THINKING;
    else if (strcmp(stateStr, "working") == 0)   newState = CLAUDY_WORKING;
    else if (strcmp(stateStr, "waiting") == 0)    newState = CLAUDY_WAITING;
    else if (strcmp(stateStr, "error") == 0)      newState = CLAUDY_ERROR;
    else if (strcmp(stateStr, "done") == 0)       newState = CLAUDY_DONE;
    else if (strcmp(stateStr, "idle") == 0)       newState = CLAUDY_IDLE;
    else if (strcmp(stateStr, "off") == 0)        newState = CLAUDY_OFF;

    if (newState != state)
    {
        state = newState;
        stateChangeTime = millis();
        showingText = true;
        dirty = true;

        // Done-state sound notification (disabled — uncomment to re-enable)
        // if (newState == CLAUDY_DONE)
        // {
        //     PeripheryManager.playRTTTLString("done:d=4,o=6,b=200:16e,16g,8a");
        // }
    }

    if (pct != contextPct)
    {
        dirty = true;
    }
    contextPct = pct;
    lastUpdateTime = millis();
}

bool ClaydyApp_::isActive()
{
    if (state == CLAUDY_OFF) return false;
    if (millis() - lastUpdateTime > IDLE_TIMEOUT) return false;
    return true;
}

void ClaydyApp_::tick()
{
    if (!isActive()) return;

    unsigned long now = millis();

    // Auto-dismiss text overlay after TEXT_DURATION
    if (showingText && (now - stateChangeTime > TEXT_DURATION))
    {
        showingText = false;
        dirty = true;
    }

    // Toggle working animation frame
    if (state == CLAUDY_WORKING && (now - lastFrameToggle > WALK_INTERVAL))
    {
        workingFrame = 1 - workingFrame;
        lastFrameToggle = now;
        dirty = true;
    }

    if (!dirty) return;
    dirty = false;

    // Draw
    DisplayManager.clearMatrix();

    uint32_t color = getStateColor();
    const uint8_t (*frame)[8] = getCurrentFrame();
    drawGhost(frame, color);

    // Right side: text or percentage + context bar
    if (showingText)
    {
        const char *label = "";
        switch (state)
        {
        case CLAUDY_THINKING: label = "THINK"; break;
        case CLAUDY_WORKING:  label = "WORK";  break;
        case CLAUDY_WAITING:  label = "WAIT";  break;
        case CLAUDY_ERROR:    label = "ERROR"; break;
        case CLAUDY_DONE:     label = "DONE";  break;
        case CLAUDY_IDLE:     label = "IDLE";  break;
        default: break;
        }
        drawStateText(label, color);
    }
    else
    {
        drawPercentage(contextPct, getCtxBrightColor(contextPct));
        drawContextBar(contextPct);
    }

    DisplayManager.show();
}
