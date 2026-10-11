const manifest = {"name":"Uran"};
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error('[@decky/api]: Failed to connect to the loader as as the loader API was not initialized. This is likely a bug in Decky Loader.');
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
}
catch {
    api = internalAPIConnection.connect(1, manifest.name);
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version 1. Some features may not work.`);
}
if (api._version != API_VERSION) {
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version ${api._version}. Some features may not work.`);
}
const callable = api.callable;
const toaster = api.toaster;
const definePlugin = (fn) => {
    return (...args) => {
        return fn(...args);
    };
};

/**
 * notify.ts — Single entry point for user-facing notifications in Uran.
 *
 * The `notification_mode` setting picks the channel:
 *   auto    -> Steam toasts in Gaming Mode, notify-send in Desktop Mode
 *   steam   -> Decky toast inside the Steam UI
 *   desktop -> notify-send via the backend
 *   none    -> dropped
 */
const NOTIFICATION_MODE_OPTIONS = [
    { data: "auto", label: "Automatic" },
    { data: "steam", label: "Steam toasts" },
    { data: "desktop", label: "Desktop (notify-send)" },
    { data: "none", label: "None" },
];
const DEFAULT_MODE = "auto";
const sendDesktopNotification = callable("send_notification");
const fetchNotificationChannel = callable("get_notification_channel");
let mode$1 = DEFAULT_MODE;
let channel = "steam";
let notifySendAvailable = true;
/**
 * Steam's own "gamepad UI is the active window" flag: true in Gaming Mode / Big Picture, false in desktop.
 */
function steamGamepadUI() {
    try {
        const store = window.SteamUIStore;
        const fn = store?.IsGamepadUIWindowActive;
        if (typeof fn === "function")
            return !!fn.call(store);
    }
    catch { }
    return null;
}
function resolveAuto() {
    const flag = steamGamepadUI();
    if (flag === null)
        return channel;
    if (flag)
        return "steam";
    return notifySendAvailable ? "desktop" : "steam";
}
function setNotificationMode(value) {
    mode$1 =
        value === "auto" ||
            value === "steam" ||
            value === "desktop" ||
            value === "none"
            ? value
            : DEFAULT_MODE;
}
function getNotificationChannel() {
    return mode$1 === "auto" ? resolveAuto() : channel;
}
/** Ask the backend which channel the current mode resolves to. */
async function refreshNotificationChannel() {
    try {
        const r = await fetchNotificationChannel(steamGamepadUI());
        notifySendAvailable = r?.notify_send !== false;
        channel =
            r?.channel === "steam" || r?.channel === "desktop" || r?.channel === "none"
                ? r.channel
                : "steam";
    }
    catch {
        channel = "steam";
    }
    return getNotificationChannel();
}
function toast(title, body) {
    toaster.toast({ title, body, duration: 5000 });
}
function notify(title, body) {
    const effective = getNotificationChannel();
    if (effective === "none")
        return;
    if (effective !== "desktop") {
        toast(title, body);
        return;
    }
    sendDesktopNotification(title, body)
        .then((r) => {
        if (r && r.ok === false)
            toast(title, body);
    })
        .catch(() => toast(title, body));
}
/** Notification body for a finished background inject job. */
function injectFinishedText(name, job) {
    if (job?.error) {
        return `Injection error for ${name}: ${job.error}`;
    }
    if (job?.manifest_error) {
        return `Injected ${name} (Manifest notice: ${job.manifest_error})`;
    }
    if (job?.keys_missing && job.keys_missing.length > 0) {
        return `Injected ${name} (${job.keys_missing.length} unkeyed depot(s))`;
    }
    return `Successfully injected ${name} into SLSsteam`;
}

var browser = {};

// can-promise has a crash in some versions of react native that dont have
// standard global objects
// https://github.com/soldair/node-qrcode/issues/157

var canPromise$1 = function () {
  return typeof Promise === 'function' && Promise.prototype && Promise.prototype.then
};

var qrcode = {};

var utils$1 = {};

let toSJISFunction;
const CODEWORDS_COUNT = [
  0, // Not used
  26, 44, 70, 100, 134, 172, 196, 242, 292, 346,
  404, 466, 532, 581, 655, 733, 815, 901, 991, 1085,
  1156, 1258, 1364, 1474, 1588, 1706, 1828, 1921, 2051, 2185,
  2323, 2465, 2611, 2761, 2876, 3034, 3196, 3362, 3532, 3706
];

/**
 * Returns the QR Code size for the specified version
 *
 * @param  {Number} version QR Code version
 * @return {Number}         size of QR code
 */
utils$1.getSymbolSize = function getSymbolSize (version) {
  if (!version) throw new Error('"version" cannot be null or undefined')
  if (version < 1 || version > 40) throw new Error('"version" should be in range from 1 to 40')
  return version * 4 + 17
};

/**
 * Returns the total number of codewords used to store data and EC information.
 *
 * @param  {Number} version QR Code version
 * @return {Number}         Data length in bits
 */
utils$1.getSymbolTotalCodewords = function getSymbolTotalCodewords (version) {
  return CODEWORDS_COUNT[version]
};

/**
 * Encode data with Bose-Chaudhuri-Hocquenghem
 *
 * @param  {Number} data Value to encode
 * @return {Number}      Encoded value
 */
utils$1.getBCHDigit = function (data) {
  let digit = 0;

  while (data !== 0) {
    digit++;
    data >>>= 1;
  }

  return digit
};

utils$1.setToSJISFunction = function setToSJISFunction (f) {
  if (typeof f !== 'function') {
    throw new Error('"toSJISFunc" is not a valid function.')
  }

  toSJISFunction = f;
};

utils$1.isKanjiModeEnabled = function () {
  return typeof toSJISFunction !== 'undefined'
};

utils$1.toSJIS = function toSJIS (kanji) {
  return toSJISFunction(kanji)
};

var errorCorrectionLevel = {};

(function (exports) {
	exports.L = { bit: 1 };
	exports.M = { bit: 0 };
	exports.Q = { bit: 3 };
	exports.H = { bit: 2 };

	function fromString (string) {
	  if (typeof string !== 'string') {
	    throw new Error('Param is not a string')
	  }

	  const lcStr = string.toLowerCase();

	  switch (lcStr) {
	    case 'l':
	    case 'low':
	      return exports.L

	    case 'm':
	    case 'medium':
	      return exports.M

	    case 'q':
	    case 'quartile':
	      return exports.Q

	    case 'h':
	    case 'high':
	      return exports.H

	    default:
	      throw new Error('Unknown EC Level: ' + string)
	  }
	}

	exports.isValid = function isValid (level) {
	  return level && typeof level.bit !== 'undefined' &&
	    level.bit >= 0 && level.bit < 4
	};

	exports.from = function from (value, defaultValue) {
	  if (exports.isValid(value)) {
	    return value
	  }

	  try {
	    return fromString(value)
	  } catch (e) {
	    return defaultValue
	  }
	}; 
} (errorCorrectionLevel));

function BitBuffer$1 () {
  this.buffer = [];
  this.length = 0;
}

BitBuffer$1.prototype = {

  get: function (index) {
    const bufIndex = Math.floor(index / 8);
    return ((this.buffer[bufIndex] >>> (7 - index % 8)) & 1) === 1
  },

  put: function (num, length) {
    for (let i = 0; i < length; i++) {
      this.putBit(((num >>> (length - i - 1)) & 1) === 1);
    }
  },

  getLengthInBits: function () {
    return this.length
  },

  putBit: function (bit) {
    const bufIndex = Math.floor(this.length / 8);
    if (this.buffer.length <= bufIndex) {
      this.buffer.push(0);
    }

    if (bit) {
      this.buffer[bufIndex] |= (0x80 >>> (this.length % 8));
    }

    this.length++;
  }
};

var bitBuffer = BitBuffer$1;

/**
 * Helper class to handle QR Code symbol modules
 *
 * @param {Number} size Symbol size
 */

function BitMatrix$1 (size) {
  if (!size || size < 1) {
    throw new Error('BitMatrix size must be defined and greater than 0')
  }

  this.size = size;
  this.data = new Uint8Array(size * size);
  this.reservedBit = new Uint8Array(size * size);
}

/**
 * Set bit value at specified location
 * If reserved flag is set, this bit will be ignored during masking process
 *
 * @param {Number}  row
 * @param {Number}  col
 * @param {Boolean} value
 * @param {Boolean} reserved
 */
BitMatrix$1.prototype.set = function (row, col, value, reserved) {
  const index = row * this.size + col;
  this.data[index] = value;
  if (reserved) this.reservedBit[index] = true;
};

/**
 * Returns bit value at specified location
 *
 * @param  {Number}  row
 * @param  {Number}  col
 * @return {Boolean}
 */
BitMatrix$1.prototype.get = function (row, col) {
  return this.data[row * this.size + col]
};

/**
 * Applies xor operator at specified location
 * (used during masking process)
 *
 * @param {Number}  row
 * @param {Number}  col
 * @param {Boolean} value
 */
BitMatrix$1.prototype.xor = function (row, col, value) {
  this.data[row * this.size + col] ^= value;
};

/**
 * Check if bit at specified location is reserved
 *
 * @param {Number}   row
 * @param {Number}   col
 * @return {Boolean}
 */
BitMatrix$1.prototype.isReserved = function (row, col) {
  return this.reservedBit[row * this.size + col]
};

var bitMatrix = BitMatrix$1;

var alignmentPattern = {};

/**
 * Alignment pattern are fixed reference pattern in defined positions
 * in a matrix symbology, which enables the decode software to re-synchronise
 * the coordinate mapping of the image modules in the event of moderate amounts
 * of distortion of the image.
 *
 * Alignment patterns are present only in QR Code symbols of version 2 or larger
 * and their number depends on the symbol version.
 */

(function (exports) {
	const getSymbolSize = utils$1.getSymbolSize;

	/**
	 * Calculate the row/column coordinates of the center module of each alignment pattern
	 * for the specified QR Code version.
	 *
	 * The alignment patterns are positioned symmetrically on either side of the diagonal
	 * running from the top left corner of the symbol to the bottom right corner.
	 *
	 * Since positions are simmetrical only half of the coordinates are returned.
	 * Each item of the array will represent in turn the x and y coordinate.
	 * @see {@link getPositions}
	 *
	 * @param  {Number} version QR Code version
	 * @return {Array}          Array of coordinate
	 */
	exports.getRowColCoords = function getRowColCoords (version) {
	  if (version === 1) return []

	  const posCount = Math.floor(version / 7) + 2;
	  const size = getSymbolSize(version);
	  const intervals = size === 145 ? 26 : Math.ceil((size - 13) / (2 * posCount - 2)) * 2;
	  const positions = [size - 7]; // Last coord is always (size - 7)

	  for (let i = 1; i < posCount - 1; i++) {
	    positions[i] = positions[i - 1] - intervals;
	  }

	  positions.push(6); // First coord is always 6

	  return positions.reverse()
	};

	/**
	 * Returns an array containing the positions of each alignment pattern.
	 * Each array's element represent the center point of the pattern as (x, y) coordinates
	 *
	 * Coordinates are calculated expanding the row/column coordinates returned by {@link getRowColCoords}
	 * and filtering out the items that overlaps with finder pattern
	 *
	 * @example
	 * For a Version 7 symbol {@link getRowColCoords} returns values 6, 22 and 38.
	 * The alignment patterns, therefore, are to be centered on (row, column)
	 * positions (6,22), (22,6), (22,22), (22,38), (38,22), (38,38).
	 * Note that the coordinates (6,6), (6,38), (38,6) are occupied by finder patterns
	 * and are not therefore used for alignment patterns.
	 *
	 * let pos = getPositions(7)
	 * // [[6,22], [22,6], [22,22], [22,38], [38,22], [38,38]]
	 *
	 * @param  {Number} version QR Code version
	 * @return {Array}          Array of coordinates
	 */
	exports.getPositions = function getPositions (version) {
	  const coords = [];
	  const pos = exports.getRowColCoords(version);
	  const posLength = pos.length;

	  for (let i = 0; i < posLength; i++) {
	    for (let j = 0; j < posLength; j++) {
	      // Skip if position is occupied by finder patterns
	      if ((i === 0 && j === 0) || // top-left
	          (i === 0 && j === posLength - 1) || // bottom-left
	          (i === posLength - 1 && j === 0)) { // top-right
	        continue
	      }

	      coords.push([pos[i], pos[j]]);
	    }
	  }

	  return coords
	}; 
} (alignmentPattern));

var finderPattern = {};

const getSymbolSize = utils$1.getSymbolSize;
const FINDER_PATTERN_SIZE = 7;

/**
 * Returns an array containing the positions of each finder pattern.
 * Each array's element represent the top-left point of the pattern as (x, y) coordinates
 *
 * @param  {Number} version QR Code version
 * @return {Array}          Array of coordinates
 */
finderPattern.getPositions = function getPositions (version) {
  const size = getSymbolSize(version);

  return [
    // top-left
    [0, 0],
    // top-right
    [size - FINDER_PATTERN_SIZE, 0],
    // bottom-left
    [0, size - FINDER_PATTERN_SIZE]
  ]
};

var maskPattern = {};

/**
 * Data mask pattern reference
 * @type {Object}
 */

(function (exports) {
	exports.Patterns = {
	  PATTERN000: 0,
	  PATTERN001: 1,
	  PATTERN010: 2,
	  PATTERN011: 3,
	  PATTERN100: 4,
	  PATTERN101: 5,
	  PATTERN110: 6,
	  PATTERN111: 7
	};

	/**
	 * Weighted penalty scores for the undesirable features
	 * @type {Object}
	 */
	const PenaltyScores = {
	  N1: 3,
	  N2: 3,
	  N3: 40,
	  N4: 10
	};

	/**
	 * Check if mask pattern value is valid
	 *
	 * @param  {Number}  mask    Mask pattern
	 * @return {Boolean}         true if valid, false otherwise
	 */
	exports.isValid = function isValid (mask) {
	  return mask != null && mask !== '' && !isNaN(mask) && mask >= 0 && mask <= 7
	};

	/**
	 * Returns mask pattern from a value.
	 * If value is not valid, returns undefined
	 *
	 * @param  {Number|String} value        Mask pattern value
	 * @return {Number}                     Valid mask pattern or undefined
	 */
	exports.from = function from (value) {
	  return exports.isValid(value) ? parseInt(value, 10) : undefined
	};

	/**
	* Find adjacent modules in row/column with the same color
	* and assign a penalty value.
	*
	* Points: N1 + i
	* i is the amount by which the number of adjacent modules of the same color exceeds 5
	*/
	exports.getPenaltyN1 = function getPenaltyN1 (data) {
	  const size = data.size;
	  let points = 0;
	  let sameCountCol = 0;
	  let sameCountRow = 0;
	  let lastCol = null;
	  let lastRow = null;

	  for (let row = 0; row < size; row++) {
	    sameCountCol = sameCountRow = 0;
	    lastCol = lastRow = null;

	    for (let col = 0; col < size; col++) {
	      let module = data.get(row, col);
	      if (module === lastCol) {
	        sameCountCol++;
	      } else {
	        if (sameCountCol >= 5) points += PenaltyScores.N1 + (sameCountCol - 5);
	        lastCol = module;
	        sameCountCol = 1;
	      }

	      module = data.get(col, row);
	      if (module === lastRow) {
	        sameCountRow++;
	      } else {
	        if (sameCountRow >= 5) points += PenaltyScores.N1 + (sameCountRow - 5);
	        lastRow = module;
	        sameCountRow = 1;
	      }
	    }

	    if (sameCountCol >= 5) points += PenaltyScores.N1 + (sameCountCol - 5);
	    if (sameCountRow >= 5) points += PenaltyScores.N1 + (sameCountRow - 5);
	  }

	  return points
	};

	/**
	 * Find 2x2 blocks with the same color and assign a penalty value
	 *
	 * Points: N2 * (m - 1) * (n - 1)
	 */
	exports.getPenaltyN2 = function getPenaltyN2 (data) {
	  const size = data.size;
	  let points = 0;

	  for (let row = 0; row < size - 1; row++) {
	    for (let col = 0; col < size - 1; col++) {
	      const last = data.get(row, col) +
	        data.get(row, col + 1) +
	        data.get(row + 1, col) +
	        data.get(row + 1, col + 1);

	      if (last === 4 || last === 0) points++;
	    }
	  }

	  return points * PenaltyScores.N2
	};

	/**
	 * Find 1:1:3:1:1 ratio (dark:light:dark:light:dark) pattern in row/column,
	 * preceded or followed by light area 4 modules wide
	 *
	 * Points: N3 * number of pattern found
	 */
	exports.getPenaltyN3 = function getPenaltyN3 (data) {
	  const size = data.size;
	  let points = 0;
	  let bitsCol = 0;
	  let bitsRow = 0;

	  for (let row = 0; row < size; row++) {
	    bitsCol = bitsRow = 0;
	    for (let col = 0; col < size; col++) {
	      bitsCol = ((bitsCol << 1) & 0x7FF) | data.get(row, col);
	      if (col >= 10 && (bitsCol === 0x5D0 || bitsCol === 0x05D)) points++;

	      bitsRow = ((bitsRow << 1) & 0x7FF) | data.get(col, row);
	      if (col >= 10 && (bitsRow === 0x5D0 || bitsRow === 0x05D)) points++;
	    }
	  }

	  return points * PenaltyScores.N3
	};

	/**
	 * Calculate proportion of dark modules in entire symbol
	 *
	 * Points: N4 * k
	 *
	 * k is the rating of the deviation of the proportion of dark modules
	 * in the symbol from 50% in steps of 5%
	 */
	exports.getPenaltyN4 = function getPenaltyN4 (data) {
	  let darkCount = 0;
	  const modulesCount = data.data.length;

	  for (let i = 0; i < modulesCount; i++) darkCount += data.data[i];

	  const k = Math.abs(Math.ceil((darkCount * 100 / modulesCount) / 5) - 10);

	  return k * PenaltyScores.N4
	};

	/**
	 * Return mask value at given position
	 *
	 * @param  {Number} maskPattern Pattern reference value
	 * @param  {Number} i           Row
	 * @param  {Number} j           Column
	 * @return {Boolean}            Mask value
	 */
	function getMaskAt (maskPattern, i, j) {
	  switch (maskPattern) {
	    case exports.Patterns.PATTERN000: return (i + j) % 2 === 0
	    case exports.Patterns.PATTERN001: return i % 2 === 0
	    case exports.Patterns.PATTERN010: return j % 3 === 0
	    case exports.Patterns.PATTERN011: return (i + j) % 3 === 0
	    case exports.Patterns.PATTERN100: return (Math.floor(i / 2) + Math.floor(j / 3)) % 2 === 0
	    case exports.Patterns.PATTERN101: return (i * j) % 2 + (i * j) % 3 === 0
	    case exports.Patterns.PATTERN110: return ((i * j) % 2 + (i * j) % 3) % 2 === 0
	    case exports.Patterns.PATTERN111: return ((i * j) % 3 + (i + j) % 2) % 2 === 0

	    default: throw new Error('bad maskPattern:' + maskPattern)
	  }
	}

	/**
	 * Apply a mask pattern to a BitMatrix
	 *
	 * @param  {Number}    pattern Pattern reference number
	 * @param  {BitMatrix} data    BitMatrix data
	 */
	exports.applyMask = function applyMask (pattern, data) {
	  const size = data.size;

	  for (let col = 0; col < size; col++) {
	    for (let row = 0; row < size; row++) {
	      if (data.isReserved(row, col)) continue
	      data.xor(row, col, getMaskAt(pattern, row, col));
	    }
	  }
	};

	/**
	 * Returns the best mask pattern for data
	 *
	 * @param  {BitMatrix} data
	 * @return {Number} Mask pattern reference number
	 */
	exports.getBestMask = function getBestMask (data, setupFormatFunc) {
	  const numPatterns = Object.keys(exports.Patterns).length;
	  let bestPattern = 0;
	  let lowerPenalty = Infinity;

	  for (let p = 0; p < numPatterns; p++) {
	    setupFormatFunc(p);
	    exports.applyMask(p, data);

	    // Calculate penalty
	    const penalty =
	      exports.getPenaltyN1(data) +
	      exports.getPenaltyN2(data) +
	      exports.getPenaltyN3(data) +
	      exports.getPenaltyN4(data);

	    // Undo previously applied mask
	    exports.applyMask(p, data);

	    if (penalty < lowerPenalty) {
	      lowerPenalty = penalty;
	      bestPattern = p;
	    }
	  }

	  return bestPattern
	}; 
} (maskPattern));

var errorCorrectionCode = {};

const ECLevel$1 = errorCorrectionLevel;

const EC_BLOCKS_TABLE = [
// L  M  Q  H
  1, 1, 1, 1,
  1, 1, 1, 1,
  1, 1, 2, 2,
  1, 2, 2, 4,
  1, 2, 4, 4,
  2, 4, 4, 4,
  2, 4, 6, 5,
  2, 4, 6, 6,
  2, 5, 8, 8,
  4, 5, 8, 8,
  4, 5, 8, 11,
  4, 8, 10, 11,
  4, 9, 12, 16,
  4, 9, 16, 16,
  6, 10, 12, 18,
  6, 10, 17, 16,
  6, 11, 16, 19,
  6, 13, 18, 21,
  7, 14, 21, 25,
  8, 16, 20, 25,
  8, 17, 23, 25,
  9, 17, 23, 34,
  9, 18, 25, 30,
  10, 20, 27, 32,
  12, 21, 29, 35,
  12, 23, 34, 37,
  12, 25, 34, 40,
  13, 26, 35, 42,
  14, 28, 38, 45,
  15, 29, 40, 48,
  16, 31, 43, 51,
  17, 33, 45, 54,
  18, 35, 48, 57,
  19, 37, 51, 60,
  19, 38, 53, 63,
  20, 40, 56, 66,
  21, 43, 59, 70,
  22, 45, 62, 74,
  24, 47, 65, 77,
  25, 49, 68, 81
];

const EC_CODEWORDS_TABLE = [
// L  M  Q  H
  7, 10, 13, 17,
  10, 16, 22, 28,
  15, 26, 36, 44,
  20, 36, 52, 64,
  26, 48, 72, 88,
  36, 64, 96, 112,
  40, 72, 108, 130,
  48, 88, 132, 156,
  60, 110, 160, 192,
  72, 130, 192, 224,
  80, 150, 224, 264,
  96, 176, 260, 308,
  104, 198, 288, 352,
  120, 216, 320, 384,
  132, 240, 360, 432,
  144, 280, 408, 480,
  168, 308, 448, 532,
  180, 338, 504, 588,
  196, 364, 546, 650,
  224, 416, 600, 700,
  224, 442, 644, 750,
  252, 476, 690, 816,
  270, 504, 750, 900,
  300, 560, 810, 960,
  312, 588, 870, 1050,
  336, 644, 952, 1110,
  360, 700, 1020, 1200,
  390, 728, 1050, 1260,
  420, 784, 1140, 1350,
  450, 812, 1200, 1440,
  480, 868, 1290, 1530,
  510, 924, 1350, 1620,
  540, 980, 1440, 1710,
  570, 1036, 1530, 1800,
  570, 1064, 1590, 1890,
  600, 1120, 1680, 1980,
  630, 1204, 1770, 2100,
  660, 1260, 1860, 2220,
  720, 1316, 1950, 2310,
  750, 1372, 2040, 2430
];

/**
 * Returns the number of error correction block that the QR Code should contain
 * for the specified version and error correction level.
 *
 * @param  {Number} version              QR Code version
 * @param  {Number} errorCorrectionLevel Error correction level
 * @return {Number}                      Number of error correction blocks
 */
errorCorrectionCode.getBlocksCount = function getBlocksCount (version, errorCorrectionLevel) {
  switch (errorCorrectionLevel) {
    case ECLevel$1.L:
      return EC_BLOCKS_TABLE[(version - 1) * 4 + 0]
    case ECLevel$1.M:
      return EC_BLOCKS_TABLE[(version - 1) * 4 + 1]
    case ECLevel$1.Q:
      return EC_BLOCKS_TABLE[(version - 1) * 4 + 2]
    case ECLevel$1.H:
      return EC_BLOCKS_TABLE[(version - 1) * 4 + 3]
    default:
      return undefined
  }
};

/**
 * Returns the number of error correction codewords to use for the specified
 * version and error correction level.
 *
 * @param  {Number} version              QR Code version
 * @param  {Number} errorCorrectionLevel Error correction level
 * @return {Number}                      Number of error correction codewords
 */
errorCorrectionCode.getTotalCodewordsCount = function getTotalCodewordsCount (version, errorCorrectionLevel) {
  switch (errorCorrectionLevel) {
    case ECLevel$1.L:
      return EC_CODEWORDS_TABLE[(version - 1) * 4 + 0]
    case ECLevel$1.M:
      return EC_CODEWORDS_TABLE[(version - 1) * 4 + 1]
    case ECLevel$1.Q:
      return EC_CODEWORDS_TABLE[(version - 1) * 4 + 2]
    case ECLevel$1.H:
      return EC_CODEWORDS_TABLE[(version - 1) * 4 + 3]
    default:
      return undefined
  }
};

var polynomial = {};

var galoisField = {};

const EXP_TABLE = new Uint8Array(512);
const LOG_TABLE = new Uint8Array(256)
/**
 * Precompute the log and anti-log tables for faster computation later
 *
 * For each possible value in the galois field 2^8, we will pre-compute
 * the logarithm and anti-logarithm (exponential) of this value
 *
 * ref {@link https://en.wikiversity.org/wiki/Reed%E2%80%93Solomon_codes_for_coders#Introduction_to_mathematical_fields}
 */
;(function initTables () {
  let x = 1;
  for (let i = 0; i < 255; i++) {
    EXP_TABLE[i] = x;
    LOG_TABLE[x] = i;

    x <<= 1; // multiply by 2

    // The QR code specification says to use byte-wise modulo 100011101 arithmetic.
    // This means that when a number is 256 or larger, it should be XORed with 0x11D.
    if (x & 0x100) { // similar to x >= 256, but a lot faster (because 0x100 == 256)
      x ^= 0x11D;
    }
  }

  // Optimization: double the size of the anti-log table so that we don't need to mod 255 to
  // stay inside the bounds (because we will mainly use this table for the multiplication of
  // two GF numbers, no more).
  // @see {@link mul}
  for (let i = 255; i < 512; i++) {
    EXP_TABLE[i] = EXP_TABLE[i - 255];
  }
}());

/**
 * Returns log value of n inside Galois Field
 *
 * @param  {Number} n
 * @return {Number}
 */
galoisField.log = function log (n) {
  if (n < 1) throw new Error('log(' + n + ')')
  return LOG_TABLE[n]
};

/**
 * Returns anti-log value of n inside Galois Field
 *
 * @param  {Number} n
 * @return {Number}
 */
galoisField.exp = function exp (n) {
  return EXP_TABLE[n]
};

/**
 * Multiplies two number inside Galois Field
 *
 * @param  {Number} x
 * @param  {Number} y
 * @return {Number}
 */
galoisField.mul = function mul (x, y) {
  if (x === 0 || y === 0) return 0

  // should be EXP_TABLE[(LOG_TABLE[x] + LOG_TABLE[y]) % 255] if EXP_TABLE wasn't oversized
  // @see {@link initTables}
  return EXP_TABLE[LOG_TABLE[x] + LOG_TABLE[y]]
};

(function (exports) {
	const GF = galoisField;

	/**
	 * Multiplies two polynomials inside Galois Field
	 *
	 * @param  {Uint8Array} p1 Polynomial
	 * @param  {Uint8Array} p2 Polynomial
	 * @return {Uint8Array}    Product of p1 and p2
	 */
	exports.mul = function mul (p1, p2) {
	  const coeff = new Uint8Array(p1.length + p2.length - 1);

	  for (let i = 0; i < p1.length; i++) {
	    for (let j = 0; j < p2.length; j++) {
	      coeff[i + j] ^= GF.mul(p1[i], p2[j]);
	    }
	  }

	  return coeff
	};

	/**
	 * Calculate the remainder of polynomials division
	 *
	 * @param  {Uint8Array} divident Polynomial
	 * @param  {Uint8Array} divisor  Polynomial
	 * @return {Uint8Array}          Remainder
	 */
	exports.mod = function mod (divident, divisor) {
	  let result = new Uint8Array(divident);

	  while ((result.length - divisor.length) >= 0) {
	    const coeff = result[0];

	    for (let i = 0; i < divisor.length; i++) {
	      result[i] ^= GF.mul(divisor[i], coeff);
	    }

	    // remove all zeros from buffer head
	    let offset = 0;
	    while (offset < result.length && result[offset] === 0) offset++;
	    result = result.slice(offset);
	  }

	  return result
	};

	/**
	 * Generate an irreducible generator polynomial of specified degree
	 * (used by Reed-Solomon encoder)
	 *
	 * @param  {Number} degree Degree of the generator polynomial
	 * @return {Uint8Array}    Buffer containing polynomial coefficients
	 */
	exports.generateECPolynomial = function generateECPolynomial (degree) {
	  let poly = new Uint8Array([1]);
	  for (let i = 0; i < degree; i++) {
	    poly = exports.mul(poly, new Uint8Array([1, GF.exp(i)]));
	  }

	  return poly
	}; 
} (polynomial));

const Polynomial = polynomial;

function ReedSolomonEncoder$1 (degree) {
  this.genPoly = undefined;
  this.degree = degree;

  if (this.degree) this.initialize(this.degree);
}

/**
 * Initialize the encoder.
 * The input param should correspond to the number of error correction codewords.
 *
 * @param  {Number} degree
 */
ReedSolomonEncoder$1.prototype.initialize = function initialize (degree) {
  // create an irreducible generator polynomial
  this.degree = degree;
  this.genPoly = Polynomial.generateECPolynomial(this.degree);
};

/**
 * Encodes a chunk of data
 *
 * @param  {Uint8Array} data Buffer containing input data
 * @return {Uint8Array}      Buffer containing encoded data
 */
ReedSolomonEncoder$1.prototype.encode = function encode (data) {
  if (!this.genPoly) {
    throw new Error('Encoder not initialized')
  }

  // Calculate EC for this data block
  // extends data size to data+genPoly size
  const paddedData = new Uint8Array(data.length + this.degree);
  paddedData.set(data);

  // The error correction codewords are the remainder after dividing the data codewords
  // by a generator polynomial
  const remainder = Polynomial.mod(paddedData, this.genPoly);

  // return EC data blocks (last n byte, where n is the degree of genPoly)
  // If coefficients number in remainder are less than genPoly degree,
  // pad with 0s to the left to reach the needed number of coefficients
  const start = this.degree - remainder.length;
  if (start > 0) {
    const buff = new Uint8Array(this.degree);
    buff.set(remainder, start);

    return buff
  }

  return remainder
};

var reedSolomonEncoder = ReedSolomonEncoder$1;

var version = {};

var mode = {};

var versionCheck = {};

/**
 * Check if QR Code version is valid
 *
 * @param  {Number}  version QR Code version
 * @return {Boolean}         true if valid version, false otherwise
 */

versionCheck.isValid = function isValid (version) {
  return !isNaN(version) && version >= 1 && version <= 40
};

var regex = {};

const numeric = '[0-9]+';
const alphanumeric = '[A-Z $%*+\\-./:]+';
let kanji = '(?:[u3000-u303F]|[u3040-u309F]|[u30A0-u30FF]|' +
  '[uFF00-uFFEF]|[u4E00-u9FAF]|[u2605-u2606]|[u2190-u2195]|u203B|' +
  '[u2010u2015u2018u2019u2025u2026u201Cu201Du2225u2260]|' +
  '[u0391-u0451]|[u00A7u00A8u00B1u00B4u00D7u00F7])+';
kanji = kanji.replace(/u/g, '\\u');

const byte = '(?:(?![A-Z0-9 $%*+\\-./:]|' + kanji + ')(?:.|[\r\n]))+';

regex.KANJI = new RegExp(kanji, 'g');
regex.BYTE_KANJI = new RegExp('[^A-Z0-9 $%*+\\-./:]+', 'g');
regex.BYTE = new RegExp(byte, 'g');
regex.NUMERIC = new RegExp(numeric, 'g');
regex.ALPHANUMERIC = new RegExp(alphanumeric, 'g');

const TEST_KANJI = new RegExp('^' + kanji + '$');
const TEST_NUMERIC = new RegExp('^' + numeric + '$');
const TEST_ALPHANUMERIC = new RegExp('^[A-Z0-9 $%*+\\-./:]+$');

regex.testKanji = function testKanji (str) {
  return TEST_KANJI.test(str)
};

regex.testNumeric = function testNumeric (str) {
  return TEST_NUMERIC.test(str)
};

regex.testAlphanumeric = function testAlphanumeric (str) {
  return TEST_ALPHANUMERIC.test(str)
};

(function (exports) {
	const VersionCheck = versionCheck;
	const Regex = regex;

	/**
	 * Numeric mode encodes data from the decimal digit set (0 - 9)
	 * (byte values 30HEX to 39HEX).
	 * Normally, 3 data characters are represented by 10 bits.
	 *
	 * @type {Object}
	 */
	exports.NUMERIC = {
	  id: 'Numeric',
	  bit: 1 << 0,
	  ccBits: [10, 12, 14]
	};

	/**
	 * Alphanumeric mode encodes data from a set of 45 characters,
	 * i.e. 10 numeric digits (0 - 9),
	 *      26 alphabetic characters (A - Z),
	 *   and 9 symbols (SP, $, %, *, +, -, ., /, :).
	 * Normally, two input characters are represented by 11 bits.
	 *
	 * @type {Object}
	 */
	exports.ALPHANUMERIC = {
	  id: 'Alphanumeric',
	  bit: 1 << 1,
	  ccBits: [9, 11, 13]
	};

	/**
	 * In byte mode, data is encoded at 8 bits per character.
	 *
	 * @type {Object}
	 */
	exports.BYTE = {
	  id: 'Byte',
	  bit: 1 << 2,
	  ccBits: [8, 16, 16]
	};

	/**
	 * The Kanji mode efficiently encodes Kanji characters in accordance with
	 * the Shift JIS system based on JIS X 0208.
	 * The Shift JIS values are shifted from the JIS X 0208 values.
	 * JIS X 0208 gives details of the shift coded representation.
	 * Each two-byte character value is compacted to a 13-bit binary codeword.
	 *
	 * @type {Object}
	 */
	exports.KANJI = {
	  id: 'Kanji',
	  bit: 1 << 3,
	  ccBits: [8, 10, 12]
	};

	/**
	 * Mixed mode will contain a sequences of data in a combination of any of
	 * the modes described above
	 *
	 * @type {Object}
	 */
	exports.MIXED = {
	  bit: -1
	};

	/**
	 * Returns the number of bits needed to store the data length
	 * according to QR Code specifications.
	 *
	 * @param  {Mode}   mode    Data mode
	 * @param  {Number} version QR Code version
	 * @return {Number}         Number of bits
	 */
	exports.getCharCountIndicator = function getCharCountIndicator (mode, version) {
	  if (!mode.ccBits) throw new Error('Invalid mode: ' + mode)

	  if (!VersionCheck.isValid(version)) {
	    throw new Error('Invalid version: ' + version)
	  }

	  if (version >= 1 && version < 10) return mode.ccBits[0]
	  else if (version < 27) return mode.ccBits[1]
	  return mode.ccBits[2]
	};

	/**
	 * Returns the most efficient mode to store the specified data
	 *
	 * @param  {String} dataStr Input data string
	 * @return {Mode}           Best mode
	 */
	exports.getBestModeForData = function getBestModeForData (dataStr) {
	  if (Regex.testNumeric(dataStr)) return exports.NUMERIC
	  else if (Regex.testAlphanumeric(dataStr)) return exports.ALPHANUMERIC
	  else if (Regex.testKanji(dataStr)) return exports.KANJI
	  else return exports.BYTE
	};

	/**
	 * Return mode name as string
	 *
	 * @param {Mode} mode Mode object
	 * @returns {String}  Mode name
	 */
	exports.toString = function toString (mode) {
	  if (mode && mode.id) return mode.id
	  throw new Error('Invalid mode')
	};

	/**
	 * Check if input param is a valid mode object
	 *
	 * @param   {Mode}    mode Mode object
	 * @returns {Boolean} True if valid mode, false otherwise
	 */
	exports.isValid = function isValid (mode) {
	  return mode && mode.bit && mode.ccBits
	};

	/**
	 * Get mode object from its name
	 *
	 * @param   {String} string Mode name
	 * @returns {Mode}          Mode object
	 */
	function fromString (string) {
	  if (typeof string !== 'string') {
	    throw new Error('Param is not a string')
	  }

	  const lcStr = string.toLowerCase();

	  switch (lcStr) {
	    case 'numeric':
	      return exports.NUMERIC
	    case 'alphanumeric':
	      return exports.ALPHANUMERIC
	    case 'kanji':
	      return exports.KANJI
	    case 'byte':
	      return exports.BYTE
	    default:
	      throw new Error('Unknown mode: ' + string)
	  }
	}

	/**
	 * Returns mode from a value.
	 * If value is not a valid mode, returns defaultValue
	 *
	 * @param  {Mode|String} value        Encoding mode
	 * @param  {Mode}        defaultValue Fallback value
	 * @return {Mode}                     Encoding mode
	 */
	exports.from = function from (value, defaultValue) {
	  if (exports.isValid(value)) {
	    return value
	  }

	  try {
	    return fromString(value)
	  } catch (e) {
	    return defaultValue
	  }
	}; 
} (mode));

(function (exports) {
	const Utils = utils$1;
	const ECCode = errorCorrectionCode;
	const ECLevel = errorCorrectionLevel;
	const Mode = mode;
	const VersionCheck = versionCheck;

	// Generator polynomial used to encode version information
	const G18 = (1 << 12) | (1 << 11) | (1 << 10) | (1 << 9) | (1 << 8) | (1 << 5) | (1 << 2) | (1 << 0);
	const G18_BCH = Utils.getBCHDigit(G18);

	function getBestVersionForDataLength (mode, length, errorCorrectionLevel) {
	  for (let currentVersion = 1; currentVersion <= 40; currentVersion++) {
	    if (length <= exports.getCapacity(currentVersion, errorCorrectionLevel, mode)) {
	      return currentVersion
	    }
	  }

	  return undefined
	}

	function getReservedBitsCount (mode, version) {
	  // Character count indicator + mode indicator bits
	  return Mode.getCharCountIndicator(mode, version) + 4
	}

	function getTotalBitsFromDataArray (segments, version) {
	  let totalBits = 0;

	  segments.forEach(function (data) {
	    const reservedBits = getReservedBitsCount(data.mode, version);
	    totalBits += reservedBits + data.getBitsLength();
	  });

	  return totalBits
	}

	function getBestVersionForMixedData (segments, errorCorrectionLevel) {
	  for (let currentVersion = 1; currentVersion <= 40; currentVersion++) {
	    const length = getTotalBitsFromDataArray(segments, currentVersion);
	    if (length <= exports.getCapacity(currentVersion, errorCorrectionLevel, Mode.MIXED)) {
	      return currentVersion
	    }
	  }

	  return undefined
	}

	/**
	 * Returns version number from a value.
	 * If value is not a valid version, returns defaultValue
	 *
	 * @param  {Number|String} value        QR Code version
	 * @param  {Number}        defaultValue Fallback value
	 * @return {Number}                     QR Code version number
	 */
	exports.from = function from (value, defaultValue) {
	  if (VersionCheck.isValid(value)) {
	    return parseInt(value, 10)
	  }

	  return defaultValue
	};

	/**
	 * Returns how much data can be stored with the specified QR code version
	 * and error correction level
	 *
	 * @param  {Number} version              QR Code version (1-40)
	 * @param  {Number} errorCorrectionLevel Error correction level
	 * @param  {Mode}   mode                 Data mode
	 * @return {Number}                      Quantity of storable data
	 */
	exports.getCapacity = function getCapacity (version, errorCorrectionLevel, mode) {
	  if (!VersionCheck.isValid(version)) {
	    throw new Error('Invalid QR Code version')
	  }

	  // Use Byte mode as default
	  if (typeof mode === 'undefined') mode = Mode.BYTE;

	  // Total codewords for this QR code version (Data + Error correction)
	  const totalCodewords = Utils.getSymbolTotalCodewords(version);

	  // Total number of error correction codewords
	  const ecTotalCodewords = ECCode.getTotalCodewordsCount(version, errorCorrectionLevel);

	  // Total number of data codewords
	  const dataTotalCodewordsBits = (totalCodewords - ecTotalCodewords) * 8;

	  if (mode === Mode.MIXED) return dataTotalCodewordsBits

	  const usableBits = dataTotalCodewordsBits - getReservedBitsCount(mode, version);

	  // Return max number of storable codewords
	  switch (mode) {
	    case Mode.NUMERIC:
	      return Math.floor((usableBits / 10) * 3)

	    case Mode.ALPHANUMERIC:
	      return Math.floor((usableBits / 11) * 2)

	    case Mode.KANJI:
	      return Math.floor(usableBits / 13)

	    case Mode.BYTE:
	    default:
	      return Math.floor(usableBits / 8)
	  }
	};

	/**
	 * Returns the minimum version needed to contain the amount of data
	 *
	 * @param  {Segment} data                    Segment of data
	 * @param  {Number} [errorCorrectionLevel=H] Error correction level
	 * @param  {Mode} mode                       Data mode
	 * @return {Number}                          QR Code version
	 */
	exports.getBestVersionForData = function getBestVersionForData (data, errorCorrectionLevel) {
	  let seg;

	  const ecl = ECLevel.from(errorCorrectionLevel, ECLevel.M);

	  if (Array.isArray(data)) {
	    if (data.length > 1) {
	      return getBestVersionForMixedData(data, ecl)
	    }

	    if (data.length === 0) {
	      return 1
	    }

	    seg = data[0];
	  } else {
	    seg = data;
	  }

	  return getBestVersionForDataLength(seg.mode, seg.getLength(), ecl)
	};

	/**
	 * Returns version information with relative error correction bits
	 *
	 * The version information is included in QR Code symbols of version 7 or larger.
	 * It consists of an 18-bit sequence containing 6 data bits,
	 * with 12 error correction bits calculated using the (18, 6) Golay code.
	 *
	 * @param  {Number} version QR Code version
	 * @return {Number}         Encoded version info bits
	 */
	exports.getEncodedBits = function getEncodedBits (version) {
	  if (!VersionCheck.isValid(version) || version < 7) {
	    throw new Error('Invalid QR Code version')
	  }

	  let d = version << 12;

	  while (Utils.getBCHDigit(d) - G18_BCH >= 0) {
	    d ^= (G18 << (Utils.getBCHDigit(d) - G18_BCH));
	  }

	  return (version << 12) | d
	}; 
} (version));

var formatInfo = {};

const Utils$3 = utils$1;

const G15 = (1 << 10) | (1 << 8) | (1 << 5) | (1 << 4) | (1 << 2) | (1 << 1) | (1 << 0);
const G15_MASK = (1 << 14) | (1 << 12) | (1 << 10) | (1 << 4) | (1 << 1);
const G15_BCH = Utils$3.getBCHDigit(G15);

/**
 * Returns format information with relative error correction bits
 *
 * The format information is a 15-bit sequence containing 5 data bits,
 * with 10 error correction bits calculated using the (15, 5) BCH code.
 *
 * @param  {Number} errorCorrectionLevel Error correction level
 * @param  {Number} mask                 Mask pattern
 * @return {Number}                      Encoded format information bits
 */
formatInfo.getEncodedBits = function getEncodedBits (errorCorrectionLevel, mask) {
  const data = ((errorCorrectionLevel.bit << 3) | mask);
  let d = data << 10;

  while (Utils$3.getBCHDigit(d) - G15_BCH >= 0) {
    d ^= (G15 << (Utils$3.getBCHDigit(d) - G15_BCH));
  }

  // xor final data with mask pattern in order to ensure that
  // no combination of Error Correction Level and data mask pattern
  // will result in an all-zero data string
  return ((data << 10) | d) ^ G15_MASK
};

var segments = {};

const Mode$4 = mode;

function NumericData (data) {
  this.mode = Mode$4.NUMERIC;
  this.data = data.toString();
}

NumericData.getBitsLength = function getBitsLength (length) {
  return 10 * Math.floor(length / 3) + ((length % 3) ? ((length % 3) * 3 + 1) : 0)
};

NumericData.prototype.getLength = function getLength () {
  return this.data.length
};

NumericData.prototype.getBitsLength = function getBitsLength () {
  return NumericData.getBitsLength(this.data.length)
};

NumericData.prototype.write = function write (bitBuffer) {
  let i, group, value;

  // The input data string is divided into groups of three digits,
  // and each group is converted to its 10-bit binary equivalent.
  for (i = 0; i + 3 <= this.data.length; i += 3) {
    group = this.data.substr(i, 3);
    value = parseInt(group, 10);

    bitBuffer.put(value, 10);
  }

  // If the number of input digits is not an exact multiple of three,
  // the final one or two digits are converted to 4 or 7 bits respectively.
  const remainingNum = this.data.length - i;
  if (remainingNum > 0) {
    group = this.data.substr(i);
    value = parseInt(group, 10);

    bitBuffer.put(value, remainingNum * 3 + 1);
  }
};

var numericData = NumericData;

const Mode$3 = mode;

/**
 * Array of characters available in alphanumeric mode
 *
 * As per QR Code specification, to each character
 * is assigned a value from 0 to 44 which in this case coincides
 * with the array index
 *
 * @type {Array}
 */
const ALPHA_NUM_CHARS = [
  '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
  'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M',
  'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z',
  ' ', '$', '%', '*', '+', '-', '.', '/', ':'
];

function AlphanumericData (data) {
  this.mode = Mode$3.ALPHANUMERIC;
  this.data = data;
}

AlphanumericData.getBitsLength = function getBitsLength (length) {
  return 11 * Math.floor(length / 2) + 6 * (length % 2)
};

AlphanumericData.prototype.getLength = function getLength () {
  return this.data.length
};

AlphanumericData.prototype.getBitsLength = function getBitsLength () {
  return AlphanumericData.getBitsLength(this.data.length)
};

AlphanumericData.prototype.write = function write (bitBuffer) {
  let i;

  // Input data characters are divided into groups of two characters
  // and encoded as 11-bit binary codes.
  for (i = 0; i + 2 <= this.data.length; i += 2) {
    // The character value of the first character is multiplied by 45
    let value = ALPHA_NUM_CHARS.indexOf(this.data[i]) * 45;

    // The character value of the second digit is added to the product
    value += ALPHA_NUM_CHARS.indexOf(this.data[i + 1]);

    // The sum is then stored as 11-bit binary number
    bitBuffer.put(value, 11);
  }

  // If the number of input data characters is not a multiple of two,
  // the character value of the final character is encoded as a 6-bit binary number.
  if (this.data.length % 2) {
    bitBuffer.put(ALPHA_NUM_CHARS.indexOf(this.data[i]), 6);
  }
};

var alphanumericData = AlphanumericData;

const Mode$2 = mode;

function ByteData (data) {
  this.mode = Mode$2.BYTE;
  if (typeof (data) === 'string') {
    this.data = new TextEncoder().encode(data);
  } else {
    this.data = new Uint8Array(data);
  }
}

ByteData.getBitsLength = function getBitsLength (length) {
  return length * 8
};

ByteData.prototype.getLength = function getLength () {
  return this.data.length
};

ByteData.prototype.getBitsLength = function getBitsLength () {
  return ByteData.getBitsLength(this.data.length)
};

ByteData.prototype.write = function (bitBuffer) {
  for (let i = 0, l = this.data.length; i < l; i++) {
    bitBuffer.put(this.data[i], 8);
  }
};

var byteData = ByteData;

const Mode$1 = mode;
const Utils$2 = utils$1;

function KanjiData (data) {
  this.mode = Mode$1.KANJI;
  this.data = data;
}

KanjiData.getBitsLength = function getBitsLength (length) {
  return length * 13
};

KanjiData.prototype.getLength = function getLength () {
  return this.data.length
};

KanjiData.prototype.getBitsLength = function getBitsLength () {
  return KanjiData.getBitsLength(this.data.length)
};

KanjiData.prototype.write = function (bitBuffer) {
  let i;

  // In the Shift JIS system, Kanji characters are represented by a two byte combination.
  // These byte values are shifted from the JIS X 0208 values.
  // JIS X 0208 gives details of the shift coded representation.
  for (i = 0; i < this.data.length; i++) {
    let value = Utils$2.toSJIS(this.data[i]);

    // For characters with Shift JIS values from 0x8140 to 0x9FFC:
    if (value >= 0x8140 && value <= 0x9FFC) {
      // Subtract 0x8140 from Shift JIS value
      value -= 0x8140;

    // For characters with Shift JIS values from 0xE040 to 0xEBBF
    } else if (value >= 0xE040 && value <= 0xEBBF) {
      // Subtract 0xC140 from Shift JIS value
      value -= 0xC140;
    } else {
      throw new Error(
        'Invalid SJIS character: ' + this.data[i] + '\n' +
        'Make sure your charset is UTF-8')
    }

    // Multiply most significant byte of result by 0xC0
    // and add least significant byte to product
    value = (((value >>> 8) & 0xff) * 0xC0) + (value & 0xff);

    // Convert result to a 13-bit binary string
    bitBuffer.put(value, 13);
  }
};

var kanjiData = KanjiData;

var dijkstra = {exports: {}};

(function (module) {

	/******************************************************************************
	 * Created 2008-08-19.
	 *
	 * Dijkstra path-finding functions. Adapted from the Dijkstar Python project.
	 *
	 * Copyright (C) 2008
	 *   Wyatt Baldwin <self@wyattbaldwin.com>
	 *   All rights reserved
	 *
	 * Licensed under the MIT license.
	 *
	 *   http://www.opensource.org/licenses/mit-license.php
	 *
	 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
	 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
	 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
	 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
	 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
	 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
	 * THE SOFTWARE.
	 *****************************************************************************/
	var dijkstra = {
	  single_source_shortest_paths: function(graph, s, d) {
	    // Predecessor map for each node that has been encountered.
	    // node ID => predecessor node ID
	    var predecessors = {};

	    // Costs of shortest paths from s to all nodes encountered.
	    // node ID => cost
	    var costs = {};
	    costs[s] = 0;

	    // Costs of shortest paths from s to all nodes encountered; differs from
	    // `costs` in that it provides easy access to the node that currently has
	    // the known shortest path from s.
	    // XXX: Do we actually need both `costs` and `open`?
	    var open = dijkstra.PriorityQueue.make();
	    open.push(s, 0);

	    var closest,
	        u, v,
	        cost_of_s_to_u,
	        adjacent_nodes,
	        cost_of_e,
	        cost_of_s_to_u_plus_cost_of_e,
	        cost_of_s_to_v,
	        first_visit;
	    while (!open.empty()) {
	      // In the nodes remaining in graph that have a known cost from s,
	      // find the node, u, that currently has the shortest path from s.
	      closest = open.pop();
	      u = closest.value;
	      cost_of_s_to_u = closest.cost;

	      // Get nodes adjacent to u...
	      adjacent_nodes = graph[u] || {};

	      // ...and explore the edges that connect u to those nodes, updating
	      // the cost of the shortest paths to any or all of those nodes as
	      // necessary. v is the node across the current edge from u.
	      for (v in adjacent_nodes) {
	        if (adjacent_nodes.hasOwnProperty(v)) {
	          // Get the cost of the edge running from u to v.
	          cost_of_e = adjacent_nodes[v];

	          // Cost of s to u plus the cost of u to v across e--this is *a*
	          // cost from s to v that may or may not be less than the current
	          // known cost to v.
	          cost_of_s_to_u_plus_cost_of_e = cost_of_s_to_u + cost_of_e;

	          // If we haven't visited v yet OR if the current known cost from s to
	          // v is greater than the new cost we just found (cost of s to u plus
	          // cost of u to v across e), update v's cost in the cost list and
	          // update v's predecessor in the predecessor list (it's now u).
	          cost_of_s_to_v = costs[v];
	          first_visit = (typeof costs[v] === 'undefined');
	          if (first_visit || cost_of_s_to_v > cost_of_s_to_u_plus_cost_of_e) {
	            costs[v] = cost_of_s_to_u_plus_cost_of_e;
	            open.push(v, cost_of_s_to_u_plus_cost_of_e);
	            predecessors[v] = u;
	          }
	        }
	      }
	    }

	    if (typeof d !== 'undefined' && typeof costs[d] === 'undefined') {
	      var msg = ['Could not find a path from ', s, ' to ', d, '.'].join('');
	      throw new Error(msg);
	    }

	    return predecessors;
	  },

	  extract_shortest_path_from_predecessor_list: function(predecessors, d) {
	    var nodes = [];
	    var u = d;
	    while (u) {
	      nodes.push(u);
	      u = predecessors[u];
	    }
	    nodes.reverse();
	    return nodes;
	  },

	  find_path: function(graph, s, d) {
	    var predecessors = dijkstra.single_source_shortest_paths(graph, s, d);
	    return dijkstra.extract_shortest_path_from_predecessor_list(
	      predecessors, d);
	  },

	  /**
	   * A very naive priority queue implementation.
	   */
	  PriorityQueue: {
	    make: function (opts) {
	      var T = dijkstra.PriorityQueue,
	          t = {},
	          key;
	      opts = opts || {};
	      for (key in T) {
	        if (T.hasOwnProperty(key)) {
	          t[key] = T[key];
	        }
	      }
	      t.queue = [];
	      t.sorter = opts.sorter || T.default_sorter;
	      return t;
	    },

	    default_sorter: function (a, b) {
	      return a.cost - b.cost;
	    },

	    /**
	     * Add a new item to the queue and ensure the highest priority element
	     * is at the front of the queue.
	     */
	    push: function (value, cost) {
	      var item = {value: value, cost: cost};
	      this.queue.push(item);
	      this.queue.sort(this.sorter);
	    },

	    /**
	     * Return the highest priority element in the queue.
	     */
	    pop: function () {
	      return this.queue.shift();
	    },

	    empty: function () {
	      return this.queue.length === 0;
	    }
	  }
	};


	// node.js module exports
	{
	  module.exports = dijkstra;
	} 
} (dijkstra));

var dijkstraExports = dijkstra.exports;

(function (exports) {
	const Mode = mode;
	const NumericData = numericData;
	const AlphanumericData = alphanumericData;
	const ByteData = byteData;
	const KanjiData = kanjiData;
	const Regex = regex;
	const Utils = utils$1;
	const dijkstra = dijkstraExports;

	/**
	 * Returns UTF8 byte length
	 *
	 * @param  {String} str Input string
	 * @return {Number}     Number of byte
	 */
	function getStringByteLength (str) {
	  return unescape(encodeURIComponent(str)).length
	}

	/**
	 * Get a list of segments of the specified mode
	 * from a string
	 *
	 * @param  {Mode}   mode Segment mode
	 * @param  {String} str  String to process
	 * @return {Array}       Array of object with segments data
	 */
	function getSegments (regex, mode, str) {
	  const segments = [];
	  let result;

	  while ((result = regex.exec(str)) !== null) {
	    segments.push({
	      data: result[0],
	      index: result.index,
	      mode: mode,
	      length: result[0].length
	    });
	  }

	  return segments
	}

	/**
	 * Extracts a series of segments with the appropriate
	 * modes from a string
	 *
	 * @param  {String} dataStr Input string
	 * @return {Array}          Array of object with segments data
	 */
	function getSegmentsFromString (dataStr) {
	  const numSegs = getSegments(Regex.NUMERIC, Mode.NUMERIC, dataStr);
	  const alphaNumSegs = getSegments(Regex.ALPHANUMERIC, Mode.ALPHANUMERIC, dataStr);
	  let byteSegs;
	  let kanjiSegs;

	  if (Utils.isKanjiModeEnabled()) {
	    byteSegs = getSegments(Regex.BYTE, Mode.BYTE, dataStr);
	    kanjiSegs = getSegments(Regex.KANJI, Mode.KANJI, dataStr);
	  } else {
	    byteSegs = getSegments(Regex.BYTE_KANJI, Mode.BYTE, dataStr);
	    kanjiSegs = [];
	  }

	  const segs = numSegs.concat(alphaNumSegs, byteSegs, kanjiSegs);

	  return segs
	    .sort(function (s1, s2) {
	      return s1.index - s2.index
	    })
	    .map(function (obj) {
	      return {
	        data: obj.data,
	        mode: obj.mode,
	        length: obj.length
	      }
	    })
	}

	/**
	 * Returns how many bits are needed to encode a string of
	 * specified length with the specified mode
	 *
	 * @param  {Number} length String length
	 * @param  {Mode} mode     Segment mode
	 * @return {Number}        Bit length
	 */
	function getSegmentBitsLength (length, mode) {
	  switch (mode) {
	    case Mode.NUMERIC:
	      return NumericData.getBitsLength(length)
	    case Mode.ALPHANUMERIC:
	      return AlphanumericData.getBitsLength(length)
	    case Mode.KANJI:
	      return KanjiData.getBitsLength(length)
	    case Mode.BYTE:
	      return ByteData.getBitsLength(length)
	  }
	}

	/**
	 * Merges adjacent segments which have the same mode
	 *
	 * @param  {Array} segs Array of object with segments data
	 * @return {Array}      Array of object with segments data
	 */
	function mergeSegments (segs) {
	  return segs.reduce(function (acc, curr) {
	    const prevSeg = acc.length - 1 >= 0 ? acc[acc.length - 1] : null;
	    if (prevSeg && prevSeg.mode === curr.mode) {
	      acc[acc.length - 1].data += curr.data;
	      return acc
	    }

	    acc.push(curr);
	    return acc
	  }, [])
	}

	/**
	 * Generates a list of all possible nodes combination which
	 * will be used to build a segments graph.
	 *
	 * Nodes are divided by groups. Each group will contain a list of all the modes
	 * in which is possible to encode the given text.
	 *
	 * For example the text '12345' can be encoded as Numeric, Alphanumeric or Byte.
	 * The group for '12345' will contain then 3 objects, one for each
	 * possible encoding mode.
	 *
	 * Each node represents a possible segment.
	 *
	 * @param  {Array} segs Array of object with segments data
	 * @return {Array}      Array of object with segments data
	 */
	function buildNodes (segs) {
	  const nodes = [];
	  for (let i = 0; i < segs.length; i++) {
	    const seg = segs[i];

	    switch (seg.mode) {
	      case Mode.NUMERIC:
	        nodes.push([seg,
	          { data: seg.data, mode: Mode.ALPHANUMERIC, length: seg.length },
	          { data: seg.data, mode: Mode.BYTE, length: seg.length }
	        ]);
	        break
	      case Mode.ALPHANUMERIC:
	        nodes.push([seg,
	          { data: seg.data, mode: Mode.BYTE, length: seg.length }
	        ]);
	        break
	      case Mode.KANJI:
	        nodes.push([seg,
	          { data: seg.data, mode: Mode.BYTE, length: getStringByteLength(seg.data) }
	        ]);
	        break
	      case Mode.BYTE:
	        nodes.push([
	          { data: seg.data, mode: Mode.BYTE, length: getStringByteLength(seg.data) }
	        ]);
	    }
	  }

	  return nodes
	}

	/**
	 * Builds a graph from a list of nodes.
	 * All segments in each node group will be connected with all the segments of
	 * the next group and so on.
	 *
	 * At each connection will be assigned a weight depending on the
	 * segment's byte length.
	 *
	 * @param  {Array} nodes    Array of object with segments data
	 * @param  {Number} version QR Code version
	 * @return {Object}         Graph of all possible segments
	 */
	function buildGraph (nodes, version) {
	  const table = {};
	  const graph = { start: {} };
	  let prevNodeIds = ['start'];

	  for (let i = 0; i < nodes.length; i++) {
	    const nodeGroup = nodes[i];
	    const currentNodeIds = [];

	    for (let j = 0; j < nodeGroup.length; j++) {
	      const node = nodeGroup[j];
	      const key = '' + i + j;

	      currentNodeIds.push(key);
	      table[key] = { node: node, lastCount: 0 };
	      graph[key] = {};

	      for (let n = 0; n < prevNodeIds.length; n++) {
	        const prevNodeId = prevNodeIds[n];

	        if (table[prevNodeId] && table[prevNodeId].node.mode === node.mode) {
	          graph[prevNodeId][key] =
	            getSegmentBitsLength(table[prevNodeId].lastCount + node.length, node.mode) -
	            getSegmentBitsLength(table[prevNodeId].lastCount, node.mode);

	          table[prevNodeId].lastCount += node.length;
	        } else {
	          if (table[prevNodeId]) table[prevNodeId].lastCount = node.length;

	          graph[prevNodeId][key] = getSegmentBitsLength(node.length, node.mode) +
	            4 + Mode.getCharCountIndicator(node.mode, version); // switch cost
	        }
	      }
	    }

	    prevNodeIds = currentNodeIds;
	  }

	  for (let n = 0; n < prevNodeIds.length; n++) {
	    graph[prevNodeIds[n]].end = 0;
	  }

	  return { map: graph, table: table }
	}

	/**
	 * Builds a segment from a specified data and mode.
	 * If a mode is not specified, the more suitable will be used.
	 *
	 * @param  {String} data             Input data
	 * @param  {Mode | String} modesHint Data mode
	 * @return {Segment}                 Segment
	 */
	function buildSingleSegment (data, modesHint) {
	  let mode;
	  const bestMode = Mode.getBestModeForData(data);

	  mode = Mode.from(modesHint, bestMode);

	  // Make sure data can be encoded
	  if (mode !== Mode.BYTE && mode.bit < bestMode.bit) {
	    throw new Error('"' + data + '"' +
	      ' cannot be encoded with mode ' + Mode.toString(mode) +
	      '.\n Suggested mode is: ' + Mode.toString(bestMode))
	  }

	  // Use Mode.BYTE if Kanji support is disabled
	  if (mode === Mode.KANJI && !Utils.isKanjiModeEnabled()) {
	    mode = Mode.BYTE;
	  }

	  switch (mode) {
	    case Mode.NUMERIC:
	      return new NumericData(data)

	    case Mode.ALPHANUMERIC:
	      return new AlphanumericData(data)

	    case Mode.KANJI:
	      return new KanjiData(data)

	    case Mode.BYTE:
	      return new ByteData(data)
	  }
	}

	/**
	 * Builds a list of segments from an array.
	 * Array can contain Strings or Objects with segment's info.
	 *
	 * For each item which is a string, will be generated a segment with the given
	 * string and the more appropriate encoding mode.
	 *
	 * For each item which is an object, will be generated a segment with the given
	 * data and mode.
	 * Objects must contain at least the property "data".
	 * If property "mode" is not present, the more suitable mode will be used.
	 *
	 * @param  {Array} array Array of objects with segments data
	 * @return {Array}       Array of Segments
	 */
	exports.fromArray = function fromArray (array) {
	  return array.reduce(function (acc, seg) {
	    if (typeof seg === 'string') {
	      acc.push(buildSingleSegment(seg, null));
	    } else if (seg.data) {
	      acc.push(buildSingleSegment(seg.data, seg.mode));
	    }

	    return acc
	  }, [])
	};

	/**
	 * Builds an optimized sequence of segments from a string,
	 * which will produce the shortest possible bitstream.
	 *
	 * @param  {String} data    Input string
	 * @param  {Number} version QR Code version
	 * @return {Array}          Array of segments
	 */
	exports.fromString = function fromString (data, version) {
	  const segs = getSegmentsFromString(data, Utils.isKanjiModeEnabled());

	  const nodes = buildNodes(segs);
	  const graph = buildGraph(nodes, version);
	  const path = dijkstra.find_path(graph.map, 'start', 'end');

	  const optimizedSegs = [];
	  for (let i = 1; i < path.length - 1; i++) {
	    optimizedSegs.push(graph.table[path[i]].node);
	  }

	  return exports.fromArray(mergeSegments(optimizedSegs))
	};

	/**
	 * Splits a string in various segments with the modes which
	 * best represent their content.
	 * The produced segments are far from being optimized.
	 * The output of this function is only used to estimate a QR Code version
	 * which may contain the data.
	 *
	 * @param  {string} data Input string
	 * @return {Array}       Array of segments
	 */
	exports.rawSplit = function rawSplit (data) {
	  return exports.fromArray(
	    getSegmentsFromString(data, Utils.isKanjiModeEnabled())
	  )
	}; 
} (segments));

const Utils$1 = utils$1;
const ECLevel = errorCorrectionLevel;
const BitBuffer = bitBuffer;
const BitMatrix = bitMatrix;
const AlignmentPattern = alignmentPattern;
const FinderPattern = finderPattern;
const MaskPattern = maskPattern;
const ECCode = errorCorrectionCode;
const ReedSolomonEncoder = reedSolomonEncoder;
const Version = version;
const FormatInfo = formatInfo;
const Mode = mode;
const Segments = segments;

/**
 * QRCode for JavaScript
 *
 * modified by Ryan Day for nodejs support
 * Copyright (c) 2011 Ryan Day
 *
 * Licensed under the MIT license:
 *   http://www.opensource.org/licenses/mit-license.php
 *
//---------------------------------------------------------------------
// QRCode for JavaScript
//
// Copyright (c) 2009 Kazuhiko Arase
//
// URL: http://www.d-project.com/
//
// Licensed under the MIT license:
//   http://www.opensource.org/licenses/mit-license.php
//
// The word "QR Code" is registered trademark of
// DENSO WAVE INCORPORATED
//   http://www.denso-wave.com/qrcode/faqpatent-e.html
//
//---------------------------------------------------------------------
*/

/**
 * Add finder patterns bits to matrix
 *
 * @param  {BitMatrix} matrix  Modules matrix
 * @param  {Number}    version QR Code version
 */
function setupFinderPattern (matrix, version) {
  const size = matrix.size;
  const pos = FinderPattern.getPositions(version);

  for (let i = 0; i < pos.length; i++) {
    const row = pos[i][0];
    const col = pos[i][1];

    for (let r = -1; r <= 7; r++) {
      if (row + r <= -1 || size <= row + r) continue

      for (let c = -1; c <= 7; c++) {
        if (col + c <= -1 || size <= col + c) continue

        if ((r >= 0 && r <= 6 && (c === 0 || c === 6)) ||
          (c >= 0 && c <= 6 && (r === 0 || r === 6)) ||
          (r >= 2 && r <= 4 && c >= 2 && c <= 4)) {
          matrix.set(row + r, col + c, true, true);
        } else {
          matrix.set(row + r, col + c, false, true);
        }
      }
    }
  }
}

/**
 * Add timing pattern bits to matrix
 *
 * Note: this function must be called before {@link setupAlignmentPattern}
 *
 * @param  {BitMatrix} matrix Modules matrix
 */
function setupTimingPattern (matrix) {
  const size = matrix.size;

  for (let r = 8; r < size - 8; r++) {
    const value = r % 2 === 0;
    matrix.set(r, 6, value, true);
    matrix.set(6, r, value, true);
  }
}

/**
 * Add alignment patterns bits to matrix
 *
 * Note: this function must be called after {@link setupTimingPattern}
 *
 * @param  {BitMatrix} matrix  Modules matrix
 * @param  {Number}    version QR Code version
 */
function setupAlignmentPattern (matrix, version) {
  const pos = AlignmentPattern.getPositions(version);

  for (let i = 0; i < pos.length; i++) {
    const row = pos[i][0];
    const col = pos[i][1];

    for (let r = -2; r <= 2; r++) {
      for (let c = -2; c <= 2; c++) {
        if (r === -2 || r === 2 || c === -2 || c === 2 ||
          (r === 0 && c === 0)) {
          matrix.set(row + r, col + c, true, true);
        } else {
          matrix.set(row + r, col + c, false, true);
        }
      }
    }
  }
}

/**
 * Add version info bits to matrix
 *
 * @param  {BitMatrix} matrix  Modules matrix
 * @param  {Number}    version QR Code version
 */
function setupVersionInfo (matrix, version) {
  const size = matrix.size;
  const bits = Version.getEncodedBits(version);
  let row, col, mod;

  for (let i = 0; i < 18; i++) {
    row = Math.floor(i / 3);
    col = i % 3 + size - 8 - 3;
    mod = ((bits >> i) & 1) === 1;

    matrix.set(row, col, mod, true);
    matrix.set(col, row, mod, true);
  }
}

/**
 * Add format info bits to matrix
 *
 * @param  {BitMatrix} matrix               Modules matrix
 * @param  {ErrorCorrectionLevel}    errorCorrectionLevel Error correction level
 * @param  {Number}    maskPattern          Mask pattern reference value
 */
function setupFormatInfo (matrix, errorCorrectionLevel, maskPattern) {
  const size = matrix.size;
  const bits = FormatInfo.getEncodedBits(errorCorrectionLevel, maskPattern);
  let i, mod;

  for (i = 0; i < 15; i++) {
    mod = ((bits >> i) & 1) === 1;

    // vertical
    if (i < 6) {
      matrix.set(i, 8, mod, true);
    } else if (i < 8) {
      matrix.set(i + 1, 8, mod, true);
    } else {
      matrix.set(size - 15 + i, 8, mod, true);
    }

    // horizontal
    if (i < 8) {
      matrix.set(8, size - i - 1, mod, true);
    } else if (i < 9) {
      matrix.set(8, 15 - i - 1 + 1, mod, true);
    } else {
      matrix.set(8, 15 - i - 1, mod, true);
    }
  }

  // fixed module
  matrix.set(size - 8, 8, 1, true);
}

/**
 * Add encoded data bits to matrix
 *
 * @param  {BitMatrix}  matrix Modules matrix
 * @param  {Uint8Array} data   Data codewords
 */
function setupData (matrix, data) {
  const size = matrix.size;
  let inc = -1;
  let row = size - 1;
  let bitIndex = 7;
  let byteIndex = 0;

  for (let col = size - 1; col > 0; col -= 2) {
    if (col === 6) col--;

    while (true) {
      for (let c = 0; c < 2; c++) {
        if (!matrix.isReserved(row, col - c)) {
          let dark = false;

          if (byteIndex < data.length) {
            dark = (((data[byteIndex] >>> bitIndex) & 1) === 1);
          }

          matrix.set(row, col - c, dark);
          bitIndex--;

          if (bitIndex === -1) {
            byteIndex++;
            bitIndex = 7;
          }
        }
      }

      row += inc;

      if (row < 0 || size <= row) {
        row -= inc;
        inc = -inc;
        break
      }
    }
  }
}

/**
 * Create encoded codewords from data input
 *
 * @param  {Number}   version              QR Code version
 * @param  {ErrorCorrectionLevel}   errorCorrectionLevel Error correction level
 * @param  {ByteData} data                 Data input
 * @return {Uint8Array}                    Buffer containing encoded codewords
 */
function createData (version, errorCorrectionLevel, segments) {
  // Prepare data buffer
  const buffer = new BitBuffer();

  segments.forEach(function (data) {
    // prefix data with mode indicator (4 bits)
    buffer.put(data.mode.bit, 4);

    // Prefix data with character count indicator.
    // The character count indicator is a string of bits that represents the
    // number of characters that are being encoded.
    // The character count indicator must be placed after the mode indicator
    // and must be a certain number of bits long, depending on the QR version
    // and data mode
    // @see {@link Mode.getCharCountIndicator}.
    buffer.put(data.getLength(), Mode.getCharCountIndicator(data.mode, version));

    // add binary data sequence to buffer
    data.write(buffer);
  });

  // Calculate required number of bits
  const totalCodewords = Utils$1.getSymbolTotalCodewords(version);
  const ecTotalCodewords = ECCode.getTotalCodewordsCount(version, errorCorrectionLevel);
  const dataTotalCodewordsBits = (totalCodewords - ecTotalCodewords) * 8;

  // Add a terminator.
  // If the bit string is shorter than the total number of required bits,
  // a terminator of up to four 0s must be added to the right side of the string.
  // If the bit string is more than four bits shorter than the required number of bits,
  // add four 0s to the end.
  if (buffer.getLengthInBits() + 4 <= dataTotalCodewordsBits) {
    buffer.put(0, 4);
  }

  // If the bit string is fewer than four bits shorter, add only the number of 0s that
  // are needed to reach the required number of bits.

  // After adding the terminator, if the number of bits in the string is not a multiple of 8,
  // pad the string on the right with 0s to make the string's length a multiple of 8.
  while (buffer.getLengthInBits() % 8 !== 0) {
    buffer.putBit(0);
  }

  // Add pad bytes if the string is still shorter than the total number of required bits.
  // Extend the buffer to fill the data capacity of the symbol corresponding to
  // the Version and Error Correction Level by adding the Pad Codewords 11101100 (0xEC)
  // and 00010001 (0x11) alternately.
  const remainingByte = (dataTotalCodewordsBits - buffer.getLengthInBits()) / 8;
  for (let i = 0; i < remainingByte; i++) {
    buffer.put(i % 2 ? 0x11 : 0xEC, 8);
  }

  return createCodewords(buffer, version, errorCorrectionLevel)
}

/**
 * Encode input data with Reed-Solomon and return codewords with
 * relative error correction bits
 *
 * @param  {BitBuffer} bitBuffer            Data to encode
 * @param  {Number}    version              QR Code version
 * @param  {ErrorCorrectionLevel} errorCorrectionLevel Error correction level
 * @return {Uint8Array}                     Buffer containing encoded codewords
 */
function createCodewords (bitBuffer, version, errorCorrectionLevel) {
  // Total codewords for this QR code version (Data + Error correction)
  const totalCodewords = Utils$1.getSymbolTotalCodewords(version);

  // Total number of error correction codewords
  const ecTotalCodewords = ECCode.getTotalCodewordsCount(version, errorCorrectionLevel);

  // Total number of data codewords
  const dataTotalCodewords = totalCodewords - ecTotalCodewords;

  // Total number of blocks
  const ecTotalBlocks = ECCode.getBlocksCount(version, errorCorrectionLevel);

  // Calculate how many blocks each group should contain
  const blocksInGroup2 = totalCodewords % ecTotalBlocks;
  const blocksInGroup1 = ecTotalBlocks - blocksInGroup2;

  const totalCodewordsInGroup1 = Math.floor(totalCodewords / ecTotalBlocks);

  const dataCodewordsInGroup1 = Math.floor(dataTotalCodewords / ecTotalBlocks);
  const dataCodewordsInGroup2 = dataCodewordsInGroup1 + 1;

  // Number of EC codewords is the same for both groups
  const ecCount = totalCodewordsInGroup1 - dataCodewordsInGroup1;

  // Initialize a Reed-Solomon encoder with a generator polynomial of degree ecCount
  const rs = new ReedSolomonEncoder(ecCount);

  let offset = 0;
  const dcData = new Array(ecTotalBlocks);
  const ecData = new Array(ecTotalBlocks);
  let maxDataSize = 0;
  const buffer = new Uint8Array(bitBuffer.buffer);

  // Divide the buffer into the required number of blocks
  for (let b = 0; b < ecTotalBlocks; b++) {
    const dataSize = b < blocksInGroup1 ? dataCodewordsInGroup1 : dataCodewordsInGroup2;

    // extract a block of data from buffer
    dcData[b] = buffer.slice(offset, offset + dataSize);

    // Calculate EC codewords for this data block
    ecData[b] = rs.encode(dcData[b]);

    offset += dataSize;
    maxDataSize = Math.max(maxDataSize, dataSize);
  }

  // Create final data
  // Interleave the data and error correction codewords from each block
  const data = new Uint8Array(totalCodewords);
  let index = 0;
  let i, r;

  // Add data codewords
  for (i = 0; i < maxDataSize; i++) {
    for (r = 0; r < ecTotalBlocks; r++) {
      if (i < dcData[r].length) {
        data[index++] = dcData[r][i];
      }
    }
  }

  // Apped EC codewords
  for (i = 0; i < ecCount; i++) {
    for (r = 0; r < ecTotalBlocks; r++) {
      data[index++] = ecData[r][i];
    }
  }

  return data
}

/**
 * Build QR Code symbol
 *
 * @param  {String} data                 Input string
 * @param  {Number} version              QR Code version
 * @param  {ErrorCorretionLevel} errorCorrectionLevel Error level
 * @param  {MaskPattern} maskPattern     Mask pattern
 * @return {Object}                      Object containing symbol data
 */
function createSymbol (data, version, errorCorrectionLevel, maskPattern) {
  let segments;

  if (Array.isArray(data)) {
    segments = Segments.fromArray(data);
  } else if (typeof data === 'string') {
    let estimatedVersion = version;

    if (!estimatedVersion) {
      const rawSegments = Segments.rawSplit(data);

      // Estimate best version that can contain raw splitted segments
      estimatedVersion = Version.getBestVersionForData(rawSegments, errorCorrectionLevel);
    }

    // Build optimized segments
    // If estimated version is undefined, try with the highest version
    segments = Segments.fromString(data, estimatedVersion || 40);
  } else {
    throw new Error('Invalid data')
  }

  // Get the min version that can contain data
  const bestVersion = Version.getBestVersionForData(segments, errorCorrectionLevel);

  // If no version is found, data cannot be stored
  if (!bestVersion) {
    throw new Error('The amount of data is too big to be stored in a QR Code')
  }

  // If not specified, use min version as default
  if (!version) {
    version = bestVersion;

  // Check if the specified version can contain the data
  } else if (version < bestVersion) {
    throw new Error('\n' +
      'The chosen QR Code version cannot contain this amount of data.\n' +
      'Minimum version required to store current data is: ' + bestVersion + '.\n'
    )
  }

  const dataBits = createData(version, errorCorrectionLevel, segments);

  // Allocate matrix buffer
  const moduleCount = Utils$1.getSymbolSize(version);
  const modules = new BitMatrix(moduleCount);

  // Add function modules
  setupFinderPattern(modules, version);
  setupTimingPattern(modules);
  setupAlignmentPattern(modules, version);

  // Add temporary dummy bits for format info just to set them as reserved.
  // This is needed to prevent these bits from being masked by {@link MaskPattern.applyMask}
  // since the masking operation must be performed only on the encoding region.
  // These blocks will be replaced with correct values later in code.
  setupFormatInfo(modules, errorCorrectionLevel, 0);

  if (version >= 7) {
    setupVersionInfo(modules, version);
  }

  // Add data codewords
  setupData(modules, dataBits);

  if (isNaN(maskPattern)) {
    // Find best mask pattern
    maskPattern = MaskPattern.getBestMask(modules,
      setupFormatInfo.bind(null, modules, errorCorrectionLevel));
  }

  // Apply mask pattern
  MaskPattern.applyMask(maskPattern, modules);

  // Replace format info bits with correct values
  setupFormatInfo(modules, errorCorrectionLevel, maskPattern);

  return {
    modules: modules,
    version: version,
    errorCorrectionLevel: errorCorrectionLevel,
    maskPattern: maskPattern,
    segments: segments
  }
}

/**
 * QR Code
 *
 * @param {String | Array} data                 Input data
 * @param {Object} options                      Optional configurations
 * @param {Number} options.version              QR Code version
 * @param {String} options.errorCorrectionLevel Error correction level
 * @param {Function} options.toSJISFunc         Helper func to convert utf8 to sjis
 */
qrcode.create = function create (data, options) {
  if (typeof data === 'undefined' || data === '') {
    throw new Error('No input text')
  }

  let errorCorrectionLevel = ECLevel.M;
  let version;
  let mask;

  if (typeof options !== 'undefined') {
    // Use higher error correction level as default
    errorCorrectionLevel = ECLevel.from(options.errorCorrectionLevel, ECLevel.M);
    version = Version.from(options.version);
    mask = MaskPattern.from(options.maskPattern);

    if (options.toSJISFunc) {
      Utils$1.setToSJISFunction(options.toSJISFunc);
    }
  }

  return createSymbol(data, version, errorCorrectionLevel, mask)
};

var canvas = {};

var utils = {};

(function (exports) {
	function hex2rgba (hex) {
	  if (typeof hex === 'number') {
	    hex = hex.toString();
	  }

	  if (typeof hex !== 'string') {
	    throw new Error('Color should be defined as hex string')
	  }

	  let hexCode = hex.slice().replace('#', '').split('');
	  if (hexCode.length < 3 || hexCode.length === 5 || hexCode.length > 8) {
	    throw new Error('Invalid hex color: ' + hex)
	  }

	  // Convert from short to long form (fff -> ffffff)
	  if (hexCode.length === 3 || hexCode.length === 4) {
	    hexCode = Array.prototype.concat.apply([], hexCode.map(function (c) {
	      return [c, c]
	    }));
	  }

	  // Add default alpha value
	  if (hexCode.length === 6) hexCode.push('F', 'F');

	  const hexValue = parseInt(hexCode.join(''), 16);

	  return {
	    r: (hexValue >> 24) & 255,
	    g: (hexValue >> 16) & 255,
	    b: (hexValue >> 8) & 255,
	    a: hexValue & 255,
	    hex: '#' + hexCode.slice(0, 6).join('')
	  }
	}

	exports.getOptions = function getOptions (options) {
	  if (!options) options = {};
	  if (!options.color) options.color = {};

	  const margin = typeof options.margin === 'undefined' ||
	    options.margin === null ||
	    options.margin < 0
	    ? 4
	    : options.margin;

	  const width = options.width && options.width >= 21 ? options.width : undefined;
	  const scale = options.scale || 4;

	  return {
	    width: width,
	    scale: width ? 4 : scale,
	    margin: margin,
	    color: {
	      dark: hex2rgba(options.color.dark || '#000000ff'),
	      light: hex2rgba(options.color.light || '#ffffffff')
	    },
	    type: options.type,
	    rendererOpts: options.rendererOpts || {}
	  }
	};

	exports.getScale = function getScale (qrSize, opts) {
	  return opts.width && opts.width >= qrSize + opts.margin * 2
	    ? opts.width / (qrSize + opts.margin * 2)
	    : opts.scale
	};

	exports.getImageWidth = function getImageWidth (qrSize, opts) {
	  const scale = exports.getScale(qrSize, opts);
	  return Math.floor((qrSize + opts.margin * 2) * scale)
	};

	exports.qrToImageData = function qrToImageData (imgData, qr, opts) {
	  const size = qr.modules.size;
	  const data = qr.modules.data;
	  const scale = exports.getScale(size, opts);
	  const symbolSize = Math.floor((size + opts.margin * 2) * scale);
	  const scaledMargin = opts.margin * scale;
	  const palette = [opts.color.light, opts.color.dark];

	  for (let i = 0; i < symbolSize; i++) {
	    for (let j = 0; j < symbolSize; j++) {
	      let posDst = (i * symbolSize + j) * 4;
	      let pxColor = opts.color.light;

	      if (i >= scaledMargin && j >= scaledMargin &&
	        i < symbolSize - scaledMargin && j < symbolSize - scaledMargin) {
	        const iSrc = Math.floor((i - scaledMargin) / scale);
	        const jSrc = Math.floor((j - scaledMargin) / scale);
	        pxColor = palette[data[iSrc * size + jSrc] ? 1 : 0];
	      }

	      imgData[posDst++] = pxColor.r;
	      imgData[posDst++] = pxColor.g;
	      imgData[posDst++] = pxColor.b;
	      imgData[posDst] = pxColor.a;
	    }
	  }
	}; 
} (utils));

(function (exports) {
	const Utils = utils;

	function clearCanvas (ctx, canvas, size) {
	  ctx.clearRect(0, 0, canvas.width, canvas.height);

	  if (!canvas.style) canvas.style = {};
	  canvas.height = size;
	  canvas.width = size;
	  canvas.style.height = size + 'px';
	  canvas.style.width = size + 'px';
	}

	function getCanvasElement () {
	  try {
	    return document.createElement('canvas')
	  } catch (e) {
	    throw new Error('You need to specify a canvas element')
	  }
	}

	exports.render = function render (qrData, canvas, options) {
	  let opts = options;
	  let canvasEl = canvas;

	  if (typeof opts === 'undefined' && (!canvas || !canvas.getContext)) {
	    opts = canvas;
	    canvas = undefined;
	  }

	  if (!canvas) {
	    canvasEl = getCanvasElement();
	  }

	  opts = Utils.getOptions(opts);
	  const size = Utils.getImageWidth(qrData.modules.size, opts);

	  const ctx = canvasEl.getContext('2d');
	  const image = ctx.createImageData(size, size);
	  Utils.qrToImageData(image.data, qrData, opts);

	  clearCanvas(ctx, canvasEl, size);
	  ctx.putImageData(image, 0, 0);

	  return canvasEl
	};

	exports.renderToDataURL = function renderToDataURL (qrData, canvas, options) {
	  let opts = options;

	  if (typeof opts === 'undefined' && (!canvas || !canvas.getContext)) {
	    opts = canvas;
	    canvas = undefined;
	  }

	  if (!opts) opts = {};

	  const canvasEl = exports.render(qrData, canvas, opts);

	  const type = opts.type || 'image/png';
	  const rendererOpts = opts.rendererOpts || {};

	  return canvasEl.toDataURL(type, rendererOpts.quality)
	}; 
} (canvas));

var svgTag = {};

const Utils = utils;

function getColorAttrib (color, attrib) {
  const alpha = color.a / 255;
  const str = attrib + '="' + color.hex + '"';

  return alpha < 1
    ? str + ' ' + attrib + '-opacity="' + alpha.toFixed(2).slice(1) + '"'
    : str
}

function svgCmd (cmd, x, y) {
  let str = cmd + x;
  if (typeof y !== 'undefined') str += ' ' + y;

  return str
}

function qrToPath (data, size, margin) {
  let path = '';
  let moveBy = 0;
  let newRow = false;
  let lineLength = 0;

  for (let i = 0; i < data.length; i++) {
    const col = Math.floor(i % size);
    const row = Math.floor(i / size);

    if (!col && !newRow) newRow = true;

    if (data[i]) {
      lineLength++;

      if (!(i > 0 && col > 0 && data[i - 1])) {
        path += newRow
          ? svgCmd('M', col + margin, 0.5 + row + margin)
          : svgCmd('m', moveBy, 0);

        moveBy = 0;
        newRow = false;
      }

      if (!(col + 1 < size && data[i + 1])) {
        path += svgCmd('h', lineLength);
        lineLength = 0;
      }
    } else {
      moveBy++;
    }
  }

  return path
}

svgTag.render = function render (qrData, options, cb) {
  const opts = Utils.getOptions(options);
  const size = qrData.modules.size;
  const data = qrData.modules.data;
  const qrcodesize = size + opts.margin * 2;

  const bg = !opts.color.light.a
    ? ''
    : '<path ' + getColorAttrib(opts.color.light, 'fill') +
      ' d="M0 0h' + qrcodesize + 'v' + qrcodesize + 'H0z"/>';

  const path =
    '<path ' + getColorAttrib(opts.color.dark, 'stroke') +
    ' d="' + qrToPath(data, size, opts.margin) + '"/>';

  const viewBox = 'viewBox="' + '0 0 ' + qrcodesize + ' ' + qrcodesize + '"';

  const width = !opts.width ? '' : 'width="' + opts.width + '" height="' + opts.width + '" ';

  const svgTag = '<svg xmlns="http://www.w3.org/2000/svg" ' + width + viewBox + ' shape-rendering="crispEdges">' + bg + path + '</svg>\n';

  if (typeof cb === 'function') {
    cb(null, svgTag);
  }

  return svgTag
};

const canPromise = canPromise$1;

const QRCode = qrcode;
const CanvasRenderer = canvas;
const SvgRenderer = svgTag;

function renderCanvas (renderFunc, canvas, text, opts, cb) {
  const args = [].slice.call(arguments, 1);
  const argsNum = args.length;
  const isLastArgCb = typeof args[argsNum - 1] === 'function';

  if (!isLastArgCb && !canPromise()) {
    throw new Error('Callback required as last argument')
  }

  if (isLastArgCb) {
    if (argsNum < 2) {
      throw new Error('Too few arguments provided')
    }

    if (argsNum === 2) {
      cb = text;
      text = canvas;
      canvas = opts = undefined;
    } else if (argsNum === 3) {
      if (canvas.getContext && typeof cb === 'undefined') {
        cb = opts;
        opts = undefined;
      } else {
        cb = opts;
        opts = text;
        text = canvas;
        canvas = undefined;
      }
    }
  } else {
    if (argsNum < 1) {
      throw new Error('Too few arguments provided')
    }

    if (argsNum === 1) {
      text = canvas;
      canvas = opts = undefined;
    } else if (argsNum === 2 && !canvas.getContext) {
      opts = text;
      text = canvas;
      canvas = undefined;
    }

    return new Promise(function (resolve, reject) {
      try {
        const data = QRCode.create(text, opts);
        resolve(renderFunc(data, canvas, opts));
      } catch (e) {
        reject(e);
      }
    })
  }

  try {
    const data = QRCode.create(text, opts);
    cb(null, renderFunc(data, canvas, opts));
  } catch (e) {
    cb(e);
  }
}

browser.create = QRCode.create;
browser.toCanvas = renderCanvas.bind(null, CanvasRenderer.render);
browser.toDataURL = renderCanvas.bind(null, CanvasRenderer.renderToDataURL);

// only svg for now.
browser.toString = renderCanvas.bind(null, function (data, _, opts) {
  return SvgRenderer.render(data, opts)
});

/**
 * StorePatch.ts — Injects "Add to ASSella" button into Steam Store webview.
 *
 * The Big Picture store is a webview (GamepadUI route /routes/steamweb -> real
 * document is store.steampowered.com). We drive it through CDP WebSocket.
 *
 * Injection target: PURCHASE OPTIONS grid. We CLONE an existing listitem
 * (which carries all of Steam's panel/focus classes and typography) and
 * relabel it, so our card looks and focuses exactly like a native one.
 *
 * A MutationObserver inside the webview re-injects immediately when
 * Steam's ReactVirtualized re-renders drop our slot, so no visible gap.
 *
 * Click detection: injected script console.log("ASSELLA:<appId>");
 * plugin reads it via CDP Runtime.consoleAPICalled.
 */
// -- Config -------------------------------------------------------------------
const POLL_MS = 2000;
const BUTTON_COLOR_BG = "#a1cd44";
const BUTTON_COLOR_TEXT = "#000000";
const ASSELLA_TAG = "ASSELLA:";
const RESTART_TAG = "RESTART:";
// -- State --------------------------------------------------------------------
let storeSocket = null;
let messageId = 1;
let wsReady = false;
let pollTimer = null;
let storePatchEnabled = null;
let stopRouteSpy = null;
let lifecycle = 0;
let lastInjectedAppId = "";
let lastConsoleTs = 0;
const addedAppIds = new Set();
const pendingAppIds = new Set();
const getInjectStatus = callable("get_inject_status");
const getSetting$1 = callable("get_setting");
const injectGame = callable("inject_game");
const restartSteam = callable("restart_steam");
const discoverStoreTab = callable("discover_store_tab");
const isAppAdded = callable("is_app_added");
const getAddedAppIds = callable("get_added_app_ids");
const feDebug$1 = callable("fe_debug");
async function syncAddedAppIds() {
    try {
        const list = await getAddedAppIds();
        if (Array.isArray(list)) {
            addedAppIds.clear();
            for (const id of list) {
                if (id)
                    addedAppIds.add(String(id));
            }
            slog(`synced ${addedAppIds.size} added games`);
        }
    }
    catch (err) {
        slog("syncAddedAppIds error: " + err);
    }
}
// -- Logging ------------------------------------------------------------------
function slog(msg) {
    try {
        void feDebug$1(`[StorePatch] ${msg}`).catch(() => { });
    }
    catch { }
    try {
        console.log("[StorePatch] " + msg);
    }
    catch { }
}
function pollInjectJob(appId, name, onDone) {
    const startedAt = Date.now();
    const MAX_WAIT_MS = 300000;
    const timer = setInterval(async () => {
        try {
            const job = await getInjectStatus(appId);
            if (job?.done) {
                clearInterval(timer);
                notify("Uran", injectFinishedText(name, job));
                onDone?.();
            }
            else if (Date.now() - startedAt > MAX_WAIT_MS) {
                clearInterval(timer);
                notify("Uran", `Background work for ${name} timed out`);
                onDone?.();
            }
        }
        catch {
            /* keep polling */
        }
    }, 2000);
}
// -- CDP WebSocket ------------------------------------------------------------
function extractAppId(url) {
    const m = url?.match(/\/app\/(\d+)/);
    return m?.[1] ?? "";
}
function wsSend(obj) {
    if (!storeSocket || storeSocket.readyState !== WebSocket.OPEN)
        return;
    storeSocket.send(JSON.stringify(obj));
}
/**
 * Injected script that runs inside the Steam Store webview.
 */
function buildInjectScript() {
    return `(function() {
    try {
      function log(msg){ try { console.log('ASSELLA-STORE:' + msg); } catch(e){} }

      var BG = ${JSON.stringify(BUTTON_COLOR_BG)};
      var FG = ${JSON.stringify(BUTTON_COLOR_TEXT)};
      var ASSELLA_TAG = ${JSON.stringify(ASSELLA_TAG)};
      var RESTART_TAG = ${JSON.stringify(RESTART_TAG)};

      function getState() {
        if (!window.__assellaStoreState) {
          window.__assellaStoreState = { appId: '', label: 'ADD TO ASSELLA', locked: false, showRestart: false };
        }
        return window.__assellaStoreState;
      }

      function makeButton(text, tag, clickLabel, disabled, isWishlistStyle, customBg, customFg) {
        var b = document.createElement('button');
        b.type = 'button';
        b.textContent = text;
        b.setAttribute('data-assella-action', tag);
        b.tabIndex = 0;
        var bg = customBg || (tag === RESTART_TAG ? '#3a3a4c' : BG);
        var fg = customFg || (tag === RESTART_TAG ? '#ffffff' : FG);
        b.style.cssText =
          (isWishlistStyle ? 'width:100%;' : '') +
          'height:36px;' +
          'background:' + bg + ';' +
          'color:' + fg + ';' +
          'border:none;' +
          'border-radius:2px;' +
          'padding:0 16px;' +
          'font-family:\"Motiva Sans\", Twemoji, \"Noto Sans\", Helvetica, sans-serif;' +
          'font-size:13px;' +
          'font-weight:700;' +
          'letter-spacing:0.3px;' +
          'box-sizing:border-box;' +
          'cursor:' + (disabled ? 'default' : 'pointer') + ';' +
          'display:' + (isWishlistStyle ? 'flex' : 'inline-flex') + ';' +
          'align-items:center;' +
          'justify-content:center;' +
          'white-space:nowrap;' +
          'opacity:' + (disabled ? '0.7' : '1') + ';' +
          'transition:filter 0.15s ease, opacity 0.15s ease;';
        if (disabled) {
          b.disabled = true;
        } else {
          b.onclick = function(e) {
            e.stopPropagation();
            e.preventDefault();
            if (clickLabel) {
              b.textContent = clickLabel;
              b.style.opacity = '0.7';
              b.disabled = true;
            }
            console.log(tag + getState().appId);
          };
          b.onmouseenter = function() {
            if (!b.disabled) b.style.filter = 'brightness(1.08)';
          };
          b.onmouseleave = function() {
            b.style.filter = 'none';
          };
        }
        return b;
      }

      function findExisting() {
        var all = document.querySelectorAll('#Uran-btns, #assella-purchase-slot');
        if (all.length > 1) {
          for (var i = 1; i < all.length; i++) {
            all[i].remove();
          }
        }
        return all[0] || null;
      }

      function updateExisting(existing) {
        if (!existing) return false;
        var S = getState();
        var slotApp = existing.getAttribute('data-assella-appid');
        if (slotApp !== S.appId) return false;

        var mainBtn = existing.querySelector('button[data-assella-action="' + ASSELLA_TAG + '"]');
        if (mainBtn) {
          mainBtn.textContent = S.label;
          mainBtn.style.opacity = S.locked ? '0.7' : '1';
          mainBtn.style.cursor = S.locked ? 'default' : 'pointer';
          mainBtn.disabled = !!S.locked;
        }

        var restart = existing.querySelector('button[data-assella-action="' + RESTART_TAG + '"]');
        if (S.showRestart && !restart) {
          var isWish = existing.classList.contains('Panel');
          existing.appendChild(makeButton('RESTART STEAM', RESTART_TAG, 'RESTARTING...', false, isWish, '#3a3a4c', '#ffffff'));
        } else if (!S.showRestart && restart) {
          restart.remove();
        }
        return true;
      }

      function createButtonWrapper(isWishlistStyle) {
        var S = getState();
        var w = document.createElement('div');
        w.id = 'Uran-btns';
        w.setAttribute('data-assella-appid', S.appId);
        w.setAttribute('data-assella-inner', '1');
        if (isWishlistStyle) {
          w.className = 'Panel Focusable';
          w.style.cssText = 'width:100%; display:flex; flex-direction:column; gap:4px;';
        } else {
          w.style.cssText = 'display:inline-flex; align-items:center; gap:6px; margin-right:6px;';
        }
        w.appendChild(makeButton(S.label, ASSELLA_TAG, 'ADDING...', S.locked, isWishlistStyle));
        if (S.showRestart) {
          w.appendChild(makeButton('RESTART STEAM', RESTART_TAG, 'RESTARTING...', false, isWishlistStyle, '#3a3a4c', '#ffffff'));
        }
        return w;
      }

      /* ------------------------------------------------------------------ */
      /* Strategy 1 (Wishlist Position): Inject under/top of wishlist button*/
      /* ------------------------------------------------------------------ */
      function injectNearWishlist() {
        var allBtns = document.querySelectorAll('button, a.btnv6_blue_hoverfade, #add_to_wishlist_area a');
        var wishBtn = null;
        for (var i = 0; i < allBtns.length; i++) {
          var b = allBtns[i];
          if (b.id === 'Uran-btns' || (b.closest && b.closest('#Uran-btns'))) continue;
          if (b.offsetHeight === 0) continue;
          var t = (b.textContent || b.getAttribute('aria-label') || '').toLowerCase();
          if (t.indexOf('wishlist') !== -1) {
            wishBtn = b;
            break;
          }
        }
        if (!wishBtn) return false;

        var colItem = wishBtn.closest ? wishBtn.closest('._2YzOLNBx6TonKU0Zmp20l4') : null;
        if (!colItem) colItem = wishBtn.parentElement;
        if (!colItem || !colItem.parentElement) return false;

        var colContainer = colItem.parentElement;
        var w = createButtonWrapper(true);

        /* Insert directly under the Wishlist button item */
        if (colItem.nextSibling) {
          colContainer.insertBefore(w, colItem.nextSibling);
        } else {
          colContainer.appendChild(w);
        }
        log('injected wishlist-style button for ' + S.appId);
        return true;
      }

      /* ------------------------------------------------------------------ */
      /* Strategy 2 (New Steam React Layout): Insert button inside the      */
      /*   purchase card right before the price and Add to Cart button      */
      /* ------------------------------------------------------------------ */
      function injectReactPurchaseRow() {
        var ft = document.getElementById('FeatureTarget_purchase-options');
        if (!ft || ft.offsetHeight === 0) return false;

        /* Find the first purchase card (base game option) */
        var card = ft.querySelector('._1F2jbNP9IHRfKonl_3baY8, [class*="_1F2jbNP9IHRfKonl"]') || ft;

        /* Find the price widget or cart button in this card */
        var priceWidget = card.querySelector('.StoreSalePriceWidgetContainer, [class*="StoreSalePriceWidgetContainer"]');
        var cartBtn = card.querySelector('button[title*="Cart" i], button[title*="CART" i], button[aria-label*="cart" i]');
        var target = priceWidget || cartBtn;
        if (!target || !target.parentElement) return false;

        var row = target.parentElement;
        var w = createButtonWrapper(false);
        row.insertBefore(w, target);
        log('injected inline button before price/cart for ' + S.appId);
        return true;
      }

      /* ------------------------------------------------------------------ */
      /* Strategy 3 (Any visible Add to Cart / Price row on the page)       */
      /* ------------------------------------------------------------------ */
      function injectNearCartButton() {
        var allBtns = document.querySelectorAll('button[title*="Cart" i], button[title*="CART" i], button[aria-label*="cart" i], button');
        var cartBtn = null;
        for (var i = 0; i < allBtns.length; i++) {
          var b = allBtns[i];
          if (b.id === 'Uran-btns' || b.closest('#Uran-btns')) continue;
          if (b.offsetHeight === 0) continue;
          var title = (b.getAttribute('title') || b.getAttribute('aria-label') || b.textContent || '').trim().toUpperCase();
          if (title.indexOf('ADD TO CART') !== -1 || title === 'ADD TO CART') {
            cartBtn = b;
            break;
          }
        }
        if (!cartBtn || !cartBtn.parentElement) return false;

        var row = cartBtn.parentElement;
        var price = row.querySelector('.StoreSalePriceWidgetContainer, [class*="StoreSalePriceWidgetContainer"], .game_purchase_price');
        var insertBeforeTarget = price || cartBtn;

        var w = createButtonWrapper(false);
        row.insertBefore(w, insertBeforeTarget);
        log('injected inline button near cart/price for ' + S.appId);
        return true;
      }

      /* ------------------------------------------------------------------ */
      /* Strategy 4 (Legacy Steam Store): .game_purchase_action             */
      /* ------------------------------------------------------------------ */
      function injectOldSteamAction() {
        var actionArea = document.querySelector('.game_purchase_action');
        if (!actionArea || actionArea.offsetHeight === 0) return false;

        var w = createButtonWrapper(false);
        if (actionArea.firstChild) {
          actionArea.insertBefore(w, actionArea.firstChild);
        } else {
          actionArea.appendChild(w);
        }
        log('injected legacy purchase action button for ' + S.appId);
        return true;
      }

      /* ------------------------------------------------------------------ */
      /* Strategy 5 (Fallback banner): prepend to purchase area             */
      /* ------------------------------------------------------------------ */
      function injectFallback() {
        var hosts = document.querySelectorAll('.game_area_purchase, #game_area_purchase, #purchaseOptionsContent');
        var host = null;
        for (var i = 0; i < hosts.length; i++) {
          if (hosts[i].offsetHeight > 0) { host = hosts[i]; break; }
        }
        if (!host) return false;

        var S = getState();
        var w = document.createElement('div');
        w.id = 'Uran-btns';
        w.setAttribute('data-assella-appid', S.appId);
        w.style.cssText = 'padding:14px; margin:12px 0; background:rgba(0,0,0,0.35); border-radius:6px; display:flex; gap:8px; align-items:center;';
        w.appendChild(makeButton(S.label, ASSELLA_TAG, 'ADDING...', S.locked, false));
        if (S.showRestart) {
          w.appendChild(makeButton('RESTART STEAM', RESTART_TAG, 'RESTARTING...', false, false, '#3a3a4c', '#ffffff'));
        }
        host.prepend(w);
        log('fallback banner injected for ' + S.appId);
        return true;
      }

      /* ------------------------------------------------------------------ */
      /* Main injection orchestrator — tries strategies in priority order    */
      /* ------------------------------------------------------------------ */
      function injectFromState() {
        var S = getState();
        if (!S.appId) return;

        var existing = findExisting();
        if (existing) {
          if (updateExisting(existing)) return;
          existing.remove();
        }

        if (injectNearWishlist()) return;
        if (injectReactPurchaseRow()) return;
        if (injectNearCartButton()) return;
        if (injectOldSteamAction()) return;
        if (injectFallback()) return;
        log('no supported purchase area found for ' + S.appId);
      }

      window.__assellaInjectFromState = injectFromState;

      if (!window.__assellaObserverInstalled) {
        window.__assellaObserverInstalled = true;
        var mo = new MutationObserver(function() {
          if (!window.__assellaStoreState || !window.__assellaStoreState.appId) return;
          var cur = findExisting();
          if (!cur) {
            window.__assellaInjectFromState();
          } else {
            updateExisting(cur);
          }
        });
        mo.observe(document.body, { childList: true, subtree: true });
        log('MutationObserver installed');
      }

      injectFromState();
    } catch(err) {
      try { console.log('ASSELLA-STORE: error ' + err); } catch(e){}
    }
  })();`;
}
/** Push current state into the webview and ask it to inject. */
async function inject(appId, force = false, labelOverride, lockedOverride) {
    if (!appId)
        return;
    if (appId === lastInjectedAppId && !force && labelOverride === undefined) {
        return;
    }
    lastInjectedAppId = appId;
    if (!addedAppIds.has(appId) && labelOverride === undefined) {
        try {
            const added = await isAppAdded(appId);
            if (added) {
                addedAppIds.add(appId);
            }
        }
        catch { }
    }
    let showRestart = false;
    try {
        const s = await getSetting$1("show_restart_button", false);
        showRestart = s === true;
    }
    catch { }
    const isAdded = addedAppIds.has(appId);
    const isPending = !isAdded && pendingAppIds.has(appId);
    const label = labelOverride ??
        (isAdded ? "ADDED" : isPending ? "ADDING..." : "ADD TO ASSELLA");
    const locked = lockedOverride ?? (isAdded || isPending);
    const stateScript = "(function(){try{" +
        "var S=window.__assellaStoreState;if(!S){S={};window.__assellaStoreState=S;}" +
        "S.appId=" +
        JSON.stringify(appId) +
        ";S.label=" +
        JSON.stringify(label) +
        ";S.locked=" +
        JSON.stringify(locked) +
        ";S.showRestart=" +
        JSON.stringify(showRestart) +
        ";}catch(e){}})();";
    wsSend({
        id: messageId++,
        method: "Runtime.evaluate",
        params: { expression: stateScript },
    });
    wsSend({
        id: messageId++,
        method: "Runtime.evaluate",
        params: { expression: buildInjectScript() },
    });
}
function remove() {
    lastInjectedAppId = "";
    wsSend({
        id: messageId++,
        method: "Runtime.evaluate",
        params: {
            expression: "(function(){try{" +
                "var s=document.querySelectorAll('#assella-purchase-slot, #Uran-btns');" +
                "for(var i=0;i<s.length;i++){s[i].remove();}" +
                "}catch(e){}})();",
        },
    });
}
async function connect(tab) {
    if (!storePatchEnabled || !tab.webSocketDebuggerUrl)
        return;
    if (storeSocket) {
        try {
            storeSocket.close();
        }
        catch { }
        storeSocket = null;
        wsReady = false;
    }
    slog("CDP: connecting to " + tab.webSocketDebuggerUrl);
    const socket = new WebSocket(tab.webSocketDebuggerUrl);
    storeSocket = socket;
    socket.onopen = () => {
        if (!storePatchEnabled || storeSocket !== socket) {
            socket.close();
            return;
        }
        wsSend({ id: messageId++, method: "Page.enable" });
        wsSend({ id: messageId++, method: "Runtime.enable" });
        syncAddedAppIds().catch(() => { });
        setTimeout(() => {
            if (!storePatchEnabled || storeSocket !== socket)
                return;
            wsReady = true;
            const appId = extractAppId(tab.url);
            if (appId)
                inject(appId, true);
        }, 1500);
    };
    socket.onmessage = (ev) => {
        if (!storePatchEnabled || storeSocket !== socket)
            return;
        try {
            const data = JSON.parse(ev.data);
            if (data.method === "Page.frameNavigated" && data.params?.frame) {
                const frame = data.params.frame;
                if (!frame.parentId) {
                    setTimeout(() => {
                        const appId = extractAppId(frame.url || "");
                        if (appId)
                            inject(appId, true);
                        else
                            remove();
                    }, 2000);
                }
            }
            if (data.method === "Runtime.consoleAPICalled" && data.params?.args) {
                const ts = typeof data.params.timestamp === "number" ? data.params.timestamp : 0;
                if (ts > 0 && ts <= lastConsoleTs) {
                    return;
                }
                if (ts > 0)
                    lastConsoleTs = ts;
                for (const arg of data.params.args) {
                    if (arg.type === "string" && arg.value) {
                        if (arg.value.startsWith("ASSELLA-STORE:")) {
                            slog("webview: " + arg.value);
                        }
                        else if (arg.value.startsWith(ASSELLA_TAG)) {
                            const appId = arg.value.slice(ASSELLA_TAG.length);
                            slog("webview click: " + appId);
                            if (addedAppIds.has(appId)) {
                                notify("Uran", `This game is already registered in your library.`);
                                inject(appId, true, "ADDED", true);
                                return;
                            }
                            pendingAppIds.add(appId);
                            inject(appId, true, "ADDING...", true);
                            injectGame(appId)
                                .then((r) => {
                                if (r && r.already_added) {
                                    pendingAppIds.delete(appId);
                                    addedAppIds.add(appId);
                                    notify("Uran", r.error || "This game is already registered in your library.");
                                    inject(appId, true, "ADDED", true);
                                    return;
                                }
                                if (r && !r.error) {
                                    const name = r.name || appId;
                                    const extra = "";
                                    const depotInfo = r.depots
                                        ? ` — ${r.depots.length} depot(s)`
                                        : "";
                                    notify("Uran", `Added ${name}${extra}${depotInfo}`);
                                    if (r.fetching) {
                                        notify("Uran", `Fetching Hubcap manifests & keys for ${name}...`);
                                    }
                                    pollInjectJob(appId, name, () => {
                                        pendingAppIds.delete(appId);
                                        addedAppIds.add(appId);
                                        inject(appId, true, "ADDED", true);
                                    });
                                }
                                else {
                                    pendingAppIds.delete(appId);
                                    notify("Uran", r?.error || `Failed to add game ${appId}`);
                                    inject(appId, true);
                                }
                            })
                                .catch((e) => {
                                pendingAppIds.delete(appId);
                                notify("Uran", `Failed to add game ${appId}: ${e}`);
                                inject(appId, true);
                            });
                        }
                        else if (arg.value.startsWith(RESTART_TAG)) {
                            restartSteam();
                        }
                    }
                }
            }
        }
        catch { }
    };
    socket.onerror = () => {
        if (storeSocket !== socket)
            return;
        slog("CDP: socket error");
        wsReady = false;
    };
    socket.onclose = () => {
        if (storeSocket !== socket)
            return;
        slog("CDP: socket closed");
        storeSocket = null;
        wsReady = false;
    };
}
async function pollCdp() {
    if (!storePatchEnabled)
        return;
    try {
        const res = await discoverStoreTab();
        if (!storePatchEnabled)
            return;
        if (res) {
            if (!storeSocket || storeSocket.readyState !== WebSocket.OPEN) {
                await connect(res);
            }
            else if (wsReady) {
                const appId = extractAppId(res.url);
                if (appId && appId !== lastInjectedAppId) {
                    inject(appId, true);
                }
            }
        }
        else {
            if (storeSocket) {
                remove();
                try {
                    storeSocket.close();
                }
                catch { }
                storeSocket = null;
                wsReady = false;
                lastInjectedAppId = "";
            }
        }
    }
    catch (e) {
        slog("pollCdp error: " + e);
    }
}
function startPoll() {
    stopPoll();
    pollCdp();
    pollTimer = setInterval(pollCdp, POLL_MS);
}
function stopPoll() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
    if (storeSocket) {
        remove();
        try {
            storeSocket.close();
        }
        catch { }
        storeSocket = null;
        wsReady = false;
    }
    lastInjectedAppId = "";
}
function initRouteSpy() {
    const origPush = history.pushState;
    const origReplace = history.replaceState;
    const report = (src) => {
        const loc = window.location;
        slog(`ROUTE-SPY[${src}] pathname=${loc.pathname} hash=${loc.hash}`);
    };
    history.pushState = function (...args) {
        const r = origPush.apply(this, args);
        report("pushState");
        return r;
    };
    history.replaceState = function (...args) {
        const r = origReplace.apply(this, args);
        report("replaceState");
        return r;
    };
    const onPop = () => report("popstate");
    const onHash = () => report("hashchange");
    window.addEventListener("popstate", onPop);
    window.addEventListener("hashchange", onHash);
    report("init");
    return () => {
        history.pushState = origPush;
        history.replaceState = origReplace;
        window.removeEventListener("popstate", onPop);
        window.removeEventListener("hashchange", onHash);
    };
}
function initStorePatch() {
    slog("initStorePatch: starting");
    syncAddedAppIds().catch(() => { });
    const thisLifecycle = ++lifecycle;
    getSetting$1("steam_store_enabled", true)
        .then((enabled) => {
        if (lifecycle === thisLifecycle)
            setStorePatchEnabled(enabled !== false);
    })
        .catch((error) => {
        slog("could not read Steam Store setting; leaving injection enabled: " + error);
        if (lifecycle === thisLifecycle)
            setStorePatchEnabled(true);
    });
    return () => {
        slog("initStorePatch: cleanup");
        lifecycle++;
        setStorePatchEnabled(false);
    };
}
function setStorePatchEnabled(enabled) {
    if (storePatchEnabled === enabled)
        return;
    storePatchEnabled = enabled;
    if (enabled) {
        slog("Steam Store button injection enabled");
        stopRouteSpy = initRouteSpy();
        startPoll();
    }
    else {
        slog("Steam Store button injection disabled");
        stopPoll();
        stopRouteSpy?.();
        stopRouteSpy = null;
    }
}

/**
 * LibraryPatch.tsx — Context menu hooks and library management actions for Uran.
 *
 * Hooks into Steam's native "Manage" context menu on games and downloads:
 *   - Add/Remove FakeAppId
 *   - Fetch DLCs (via Hubcap API)
 *   - Fetch/Update Manifests (via Hubcap API)
 *   - Remove Pinned Manifests
 *   - Why is this game not downloading? (diagnostic check)
 */

const SP_REACT$1 = window.SP_REACT;
const h = SP_REACT$1?.createElement?.bind(SP_REACT$1);
const getFakeAppIds = callable("get_fake_app_ids");
const addFakeAppId = callable("add_fake_app_id");
const removeFakeAppId = callable("remove_fake_app_id");
const refetchManifests = callable("refetch_manifests");
const whyNotDownloading = callable("why_not_downloading");
const removeManifestIdPins = callable("remove_manifest_id_pins");
const fetchDlcs = callable("fetch_dlcs_for_app");
const feDebug = callable("fe_debug");
function feLog(msg) {
    try {
        feDebug(msg);
    }
    catch { }
    try {
        console.log("[ASSella Library] " + msg);
    }
    catch { }
}
const fakeAppIdsCache = new Set();
async function refreshFakeAppIds() {
    try {
        const res = await getFakeAppIds();
        fakeAppIdsCache.clear();
        (res?.ids || []).forEach((id) => fakeAppIdsCache.add(id));
    }
    catch { }
}
// Initial cache load
refreshFakeAppIds();
// -- Context Menu Patch (Manage submenu) -------------------------------------
let _contextMenuPatches = [];
function appIdFromMenuElement(element) {
    const props = element?.props;
    if (!props)
        return "";
    for (const candidate of [props.overview, props.app, props.item, props]) {
        const appid = candidate?.appid;
        if (appid)
            return String(appid);
    }
    return "";
}
function initContextMenuPatch() {
    const MenuInstanceClass = DFL.findModuleExport((e) => {
        if (!e || typeof e !== "function" || !e.prototype)
            return false;
        const p = e.prototype;
        return (typeof p.ShowMenu === "function" &&
            typeof p.HideMenu === "function" &&
            typeof p.ShowSubMenu === "function");
    });
    if (!MenuInstanceClass) {
        feLog("initContextMenuPatch: MenuInstanceClass not found");
        return () => { };
    }
    const baseProto = MenuInstanceClass.prototype;
    if (!baseProto || typeof baseProto.ShowSubMenu !== "function") {
        feLog("initContextMenuPatch: ShowSubMenu not found on prototype");
        return () => { };
    }
    feLog("initContextMenuPatch: hooking base ShowSubMenu");
    const isAssellaItem = (c) => c?.props?.["data-assella-fakeappid"] ||
        c?.props?.["data-assella-fetch-decryption-keys"] ||
        c?.props?.["data-assella-fetch-dlcs"] ||
        c?.props?.["data-assella-fetch-manifest"] ||
        c?.props?.["data-assella-remove-manifest-pins"] ||
        c?.props?.["data-assella-why-not-downloading"] ||
        c?.props?.["data-assella-remove-installed-depots"];
    const origShowSubMenu = baseProto.ShowSubMenu;
    baseProto.ShowSubMenu = function (element, renderFn, ...rest) {
        try {
            const appId = appIdFromMenuElement(this?.ReactElement);
            if (appId && typeof renderFn === "function") {
                const origRender = renderFn;
                const wrappedRender = () => {
                    const el = origRender();
                    const kids = el?.props?.children;
                    if (!Array.isArray(kids))
                        return el;
                    const isShortcut = parseInt(appId, 10) >= 1000000000;
                    const menuTexts = (() => {
                        const found = { uninstall: false, remove: false };
                        const stack = [...kids];
                        while (stack.length > 0) {
                            const node = stack.pop();
                            if (!node)
                                continue;
                            const text = node?.props?.children;
                            if (typeof text === "string") {
                                if (text.includes("Uninstall"))
                                    found.uninstall = true;
                                if (text.includes("Remove non-Steam game"))
                                    found.remove = true;
                            }
                            const sub = node?.props?.children;
                            if (Array.isArray(sub))
                                stack.push(...sub);
                            else if (sub && typeof sub === "object")
                                stack.push(sub);
                        }
                        return found;
                    })();
                    const isManageMenu = el?.props?.label === "Manage" ||
                        menuTexts.uninstall ||
                        (isShortcut && menuTexts.remove);
                    if (!isManageMenu)
                        return el;
                    const isFake = fakeAppIdsCache.has(appId);
                    const fakeMenuItem = h(DFL.MenuItem, {
                        key: "assella-fakeappid",
                        "data-assella-fakeappid": appId,
                        onSelected: async () => {
                            try {
                                if (isFake) {
                                    const r = await removeFakeAppId(appId);
                                    if (r?.ok) {
                                        fakeAppIdsCache.delete(appId);
                                        notify("Uran", `Removed FakeAppid for ${appId}`);
                                    }
                                    else {
                                        notify("Uran", r?.error || "Failed to remove FakeAppid");
                                    }
                                }
                                else {
                                    const r = await addFakeAppId(appId);
                                    if (r?.ok) {
                                        fakeAppIdsCache.add(appId);
                                        const msg = r?.already
                                            ? `FakeAppid already set for ${appId}`
                                            : `FakeAppid added for ${appId}: 480`;
                                        notify("Uran", msg);
                                    }
                                    else {
                                        notify("Uran", r?.error || "Failed to add FakeAppid");
                                    }
                                }
                            }
                            catch (e) {
                                notify("Uran", `Error: ${e}`);
                            }
                        },
                    }, isFake ? "Remove FakeAppid" : "Add FakeAppid (480)");
                    const fetchDlcsMenuItem = h(DFL.MenuItem, {
                        key: "assella-fetch-dlcs",
                        "data-assella-fetch-dlcs": appId,
                        onSelected: async () => {
                            try {
                                notify("Uran", `Fetching DLCs for ${appId}...`);
                                const r = await fetchDlcs(appId);
                                if (r?.ok) {
                                    const count = r.count ?? 0;
                                    if (count === 0) {
                                        notify("Uran", `No DLCs found for ${appId}`);
                                    }
                                    else {
                                        const apps = r.apps_added?.length ?? 0;
                                        const depots = r.depots_added?.length ?? 0;
                                        const keys = r.keys_added?.length ?? 0;
                                        const skipped = r.skipped_dlcs?.length ?? 0;
                                        const parts = [];
                                        if (apps > 0)
                                            parts.push(`${apps} app(s)`);
                                        if (depots > 0)
                                            parts.push(`${depots} depot(s)`);
                                        if (keys > 0)
                                            parts.push(`${keys} key(s)`);
                                        const summary = parts.length > 0
                                            ? `Added: ${parts.join(", ")}`
                                            : "DLCs already configured";
                                        const skipNote = skipped > 0 ? ` (${skipped} skipped)` : "";
                                        notify("Uran", `Found ${count} DLC(s) for ${appId}. ${summary}${skipNote}`);
                                    }
                                }
                                else {
                                    notify("Uran", r?.error || `Failed to fetch DLCs for ${appId}`);
                                }
                            }
                            catch (e) {
                                notify("Uran", `Error: ${e}`);
                            }
                        },
                    }, "Fetch DLCs");
                    const fetchManifestMenuItem = h(DFL.MenuItem, {
                        key: "assella-fetch-manifest",
                        "data-assella-fetch-manifest": appId,
                        onSelected: async () => {
                            try {
                                notify("Uran", `Fetching Hubcap manifest bundle for ${appId}...`);
                                const r = await refetchManifests(appId);
                                if (r?.ok) {
                                    const written = r.written ?? 0;
                                    const manifests = r.manifests || [];
                                    const pins = r.manifest_ids
                                        ? Object.keys(r.manifest_ids).length
                                        : 0;
                                    const pinMsg = pins > 0 ? `, pinned ${pins} depot manifest(s)` : "";
                                    const clearedPins = r.removed_pins?.length ?? 0;
                                    const clearedMsg = clearedPins > 0
                                        ? ` (cleared ${clearedPins} old pin(s))`
                                        : "";
                                    notify("Uran", manifests.length > 0
                                        ? `Extracted ${written} manifest(s) to depotcache${pinMsg}${clearedMsg}`
                                        : "Manifest bundle downloaded and parsed");
                                }
                                else {
                                    notify("Uran", r?.error || `Failed to fetch manifest for ${appId}`);
                                }
                            }
                            catch (e) {
                                notify("Uran", `Error: ${e}`);
                            }
                        },
                    }, "Fetch manifest (Hubcap)");
                    const removeManifestPinsMenuItem = h(DFL.MenuItem, {
                        key: "assella-remove-manifest-pins",
                        "data-assella-remove-manifest-pins": appId,
                        onSelected: async () => {
                            try {
                                const r = await removeManifestIdPins(appId);
                                if (r?.ok) {
                                    const count = r.removed_pins?.length ?? 0;
                                    notify("Uran", count > 0
                                        ? `Removed ${count} pinned manifest(s) for ${appId}`
                                        : `No pinned manifests found for ${appId}`);
                                }
                                else {
                                    notify("Uran", r?.error || `Failed to remove manifest pins for ${appId}`);
                                }
                            }
                            catch (e) {
                                notify("Uran", `Error: ${e}`);
                            }
                        },
                    }, "Remove pinned manifests");
                    const whyNotDownloadingMenuItem = h(DFL.MenuItem, {
                        key: "assella-why-not-downloading",
                        "data-assella-why-not-downloading": appId,
                        onSelected: async () => {
                            try {
                                const r = await whyNotDownloading(appId);
                                if (r?.ok && r.message) {
                                    notify("Uran", r.message);
                                }
                                else {
                                    notify("Uran", r?.error || `Could not inspect app ${appId}`);
                                }
                            }
                            catch (e) {
                                notify("Uran", `Error: ${e}`);
                            }
                        },
                    }, "Why not downloading?");
                    // Remove any duplicate instances before injecting
                    const filteredKids = kids.filter((c) => !isAssellaItem(c));
                    // Place our ASSella items at the beginning of the Manage menu
                    const assellaItems = [
                        fakeMenuItem,
                        fetchDlcsMenuItem,
                        fetchManifestMenuItem,
                        removeManifestPinsMenuItem,
                        whyNotDownloadingMenuItem,
                    ];
                    return {
                        ...el,
                        props: {
                            ...el.props,
                            children: [...assellaItems, ...filteredKids],
                        },
                    };
                };
                return origShowSubMenu.call(this, element, wrappedRender, ...rest);
            }
        }
        catch (e) {
            feLog("ShowSubMenu hook error: " + e);
        }
        return origShowSubMenu.call(this, element, renderFn, ...rest);
    };
    _contextMenuPatches.push(() => {
        baseProto.ShowSubMenu = origShowSubMenu;
    });
    return () => {
        _contextMenuPatches.forEach((unpatch) => unpatch());
        _contextMenuPatches = [];
    };
}

const AssellaLogo = ({ size = "1em", style, }) => (SP_JSX.jsxs("svg", { viewBox: "0 0 100 100", width: size, height: size, style: { display: "inline-block", verticalAlign: "middle", ...style }, xmlns: "http://www.w3.org/2000/svg", children: [SP_JSX.jsx("path", { d: "M20.956 50.804 L49.999 16.921 L79.025 50.826 C85.468 58.562 84.421 70.081 76.679 76.52 C68.909 82.998 57.43 81.891 50.936 74.175 C50.435 73.58 49.516 73.582 49.018 74.181 C42.577 81.925 31.053 82.967 23.319 76.519 C15.559 70.065 14.558 58.574 20.956 50.804 Z", fill: "#f4c8ab" }), SP_JSX.jsx("path", { d: "M49.051 14.187 C49.55 13.605 50.451 13.605 50.95 14.187 L80.93 49.207 C80.933 49.211 80.937 49.215 80.94 49.22 C88.272 58.013 87.086 71.117 78.28 78.44 C69.88 85.444 57.551 84.695 49.985 76.851 C42.461 84.72 30.094 85.422 21.721 78.441 C12.899 71.105 11.754 58.036 19.036 49.205 C19.041 49.199 19.046 49.193 19.051 49.187 Z M49.999 16.921 L20.957 50.804 C14.558 58.574 15.559 70.065 23.319 76.519 C31.054 82.968 42.578 81.926 49.019 74.181 C49.516 73.583 50.435 73.58 50.936 74.175 C57.431 81.891 68.91 82.998 76.68 76.52 C84.422 70.081 85.469 58.562 79.025 50.827 Z", fill: "#000000" }), SP_JSX.jsx("path", { d: "M26.9 42 C42.3 46 57.7 46 73.1 42 C61.033 54 53.333 65 50 75 C46.667 65 38.967 54 26.9 42 Z", fill: "#000000" }), SP_JSX.jsx("path", { d: "M72.762 56.826 C72.858 56.142 73.49 55.666 74.174 55.762 C74.858 55.858 75.334 56.49 75.238 57.174 C74.486 62.529 70.557 66.922 65.298 68.214 C64.628 68.379 63.951 67.969 63.786 67.298 C63.621 66.628 64.031 65.951 64.702 65.786 C68.968 64.738 72.152 61.169 72.762 56.826 Z", fill: "#000000" })] }));
const TrashIcon = ({ size = "1em", style, }) => (SP_JSX.jsxs("svg", { viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", style: { display: "inline-block", verticalAlign: "middle", ...style }, children: [SP_JSX.jsx("polyline", { points: "3 6 5 6 21 6" }), SP_JSX.jsx("path", { d: "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" }), SP_JSX.jsx("line", { x1: "10", y1: "11", x2: "10", y2: "17" }), SP_JSX.jsx("line", { x1: "14", y1: "11", x2: "14", y2: "17" })] }));
const getRecentInjects = callable("get_recent_injects");
const searchGames = callable("search_games");
callable("inject_game");
const getSetting = callable("get_setting");
const setSetting = callable("set_setting");
const listBackups = callable("list_backups");
const createBackup = callable("create_backup");
const restoreBackup = callable("restore_backup");
callable("get_hubcap_key_status");
const startKeyServer = callable("start_key_server");
const keyServerStatus = callable("key_server_status");
const stopKeyServer = callable("stop_key_server");
callable("validate_hubcap_key");
callable("save_hubcap_key");
const getHubcapUserStats = callable("get_hubcap_user_stats");
// -- AT0M game management --
const listAtomGames = callable("list_plugin_games");
const getAtomGame = callable("get_atom_game");
const previewAtomUninstall = callable("preview_atom_uninstall");
const uninstallAtomGame = callable("uninstall_atom_game");
const getStoreDebugStatus = callable("get_store_debug_status");
const setSlsonline = callable("set_slsonline");
const setNetsock = callable("set_netsock_toggle");
const setEos = callable("set_eos_toggle");
const setEosNetsock = callable("set_eos_netsock");
const toggleGameDlcs = callable("toggle_game_dlcs");
callable("get_inject_status");
// -- Search Tab ---------------------------------------------------------------
const SearchTab = () => {
    const [query, setQuery] = SP_REACT.useState("");
    const [searchByAppId, setSearchByAppId] = SP_REACT.useState(false);
    const [results, setResults] = SP_REACT.useState([]);
    const [searching, setSearching] = SP_REACT.useState(false);
    const [msg, setMsg] = SP_REACT.useState("");
    const [recent, setRecent] = SP_REACT.useState([]);
    SP_REACT.useReducer((n) => n + 1, 0);
    const loadRecent = async () => {
        try {
            const r = await getRecentInjects();
            setRecent(r ?? []);
        }
        catch { }
    };
    SP_REACT.useEffect(() => {
        loadRecent();
        const t = setInterval(loadRecent, 5000);
        return () => clearInterval(t);
    }, []);
    const doSearch = async () => {
        const q = query.trim();
        const minLen = searchByAppId ? 1 : 3;
        if (q.length < minLen) {
            setMsg(searchByAppId ? "Enter an App ID" : "Enter at least 3 characters");
            return;
        }
        setSearching(true);
        setMsg("");
        try {
            const r = await searchGames(q, 20, searchByAppId);
            if (r?.error) {
                setMsg(r.error);
                setResults([]);
            }
            else {
                const res = r?.results ?? [];
                setResults(res);
                setMsg(res.length === 0
                    ? "No results found"
                    : `${res.length} result${res.length !== 1 ? "s" : ""}`);
            }
        }
        catch (e) {
            setMsg(`Search error: ${e}`);
            setResults([]);
        }
        setSearching(false);
    };
    return (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsxs(DFL.PanelSection, { title: "Search Games", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.TextField, { label: searchByAppId ? "App ID (numeric)" : "Game Name", value: query, onChange: (e) => setQuery(e.target.value) }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Search by App ID", description: "Match exact game_id instead of name", checked: searchByAppId, onChange: setSearchByAppId }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: searching || query.trim().length < (searchByAppId ? 1 : 3), onClick: doSearch, children: searching ? "Searching..." : "Search" }) })] }), msg && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: { fontSize: "12px", opacity: 0.8, padding: "8px" }, children: msg }) }))] }));
};
const formatBytes = (n) => {
    if (!n)
        return "";
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let v = n;
    while (v >= 1024 && i < u.length - 1) {
        v /= 1024;
        i++;
    }
    return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
};
const AtomGamesTab = () => {
    const [games, setGames] = SP_REACT.useState([]);
    const [loading, setLoading] = SP_REACT.useState(true);
    const [detail, setDetail] = SP_REACT.useState(null);
    const [busy, setBusy] = SP_REACT.useState(false);
    const [msg, setMsg] = SP_REACT.useState("");
    const load = SP_REACT.useCallback(async () => {
        try {
            const r = await listAtomGames();
            setGames(r?.games ?? []);
            syncAddedAppIds().catch(() => { });
        }
        catch {
            setGames([]);
        }
        finally {
            setLoading(false);
        }
    }, []);
    SP_REACT.useEffect(() => {
        load();
    }, [load]);
    const openGame = async (appId) => {
        setMsg("");
        try {
            const d = await getAtomGame(appId);
            if (d?.ok)
                setDetail(d);
            else
                setMsg(d?.error || "Could not open game");
        }
        catch (e) {
            setMsg(`Error: ${e}`);
        }
    };
    const refreshDetail = async () => {
        if (detail)
            await openGame(detail.app_id);
    };
    const toggle = async (label, fn) => {
        setBusy(true);
        setMsg("");
        try {
            const r = await fn();
            if (!r?.ok)
                setMsg(r?.error || `${label} failed`);
            else
                setMsg(`${label} updated`);
            await refreshDetail();
        }
        catch (e) {
            setMsg(`Error: ${e}`);
        }
        finally {
            setBusy(false);
        }
    };
    const askUninstall = async (g) => {
        setBusy(true);
        try {
            const p = await previewAtomUninstall(g.app_id);
            if (p?.ok) {
                const targets = p.targets || [];
                let modal;
                modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: `Uninstall ${g.name}?`, strOKButtonText: "Uninstall", strCancelButtonText: "Cancel", bDestructiveWarning: true, bDisableBackgroundDismiss: true, onCancel: () => modal.Close(), onOK: () => {
                        modal.Close();
                        void doUninstall(g);
                    }, children: SP_JSX.jsxs("div", { style: { maxHeight: "45vh", overflowY: "auto", fontSize: "12px" }, children: [SP_JSX.jsx("p", { children: "This permanently deletes these files and folders:" }), targets.length ? (SP_JSX.jsx("ul", { style: { margin: "6px 0", paddingLeft: "18px" }, children: targets.map((target) => (SP_JSX.jsx("li", { style: { fontSize: "11px", wordBreak: "break-all" }, children: target }, target))) })) : (SP_JSX.jsx("p", { children: "No game files were found. Uran will only remove its library and config entries." })), SP_JSX.jsx("p", { children: "It will also remove this game from SLSsteam's config." }), SP_JSX.jsx("p", { style: { color: "#e57373" }, children: "This cannot be undone." })] }) }), undefined, { strTitle: `Uninstall ${g.name}?`, bNeverPopOut: true });
            }
            else
                setMsg(p?.error || "Could not prepare uninstall");
        }
        catch (e) {
            setMsg(`Error: ${e}`);
        }
        finally {
            setBusy(false);
        }
    };
    const doUninstall = async (game) => {
        setBusy(true);
        setMsg("");
        try {
            const r = await uninstallAtomGame(game.app_id);
            if (r?.ok) {
                addedAppIds.delete(game.app_id);
                notify("Uran", `Uninstalled ${game.name}`);
                setMsg(`Uninstalled ${game.name}`);
                setDetail(null);
                await load();
            }
            else {
                const issues = [...(r?.failed || [])];
                if (r?.config_cleaned === false)
                    issues.push("SLSsteam config cleanup failed");
                if (r?.registered)
                    issues.push("game is still registered in Uran");
                setMsg(`Uninstall incomplete: ${issues.join("; ") || r?.error || "unknown error"}`);
                await load();
            }
        }
        catch (e) {
            setMsg(`Error: ${e}`);
        }
        finally {
            setBusy(false);
        }
    };
    // ---- Detail page ----
    if (detail) {
        const notInstalled = !detail.installed;
        return (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSection, { children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => {
                                setDetail(null);
                                setMsg("");
                            }, children: "\u2190 Back to games" }) }) }), SP_JSX.jsx(DFL.PanelSection, { title: detail.name, children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { fontSize: "13px", lineHeight: 1.8 }, children: [SP_JSX.jsxs("div", { children: ["AppID ", SP_JSX.jsx("b", { children: detail.app_id })] }), detail.installed && detail.size_on_disk > 0 && (SP_JSX.jsxs("div", { children: ["Size: ", formatBytes(detail.size_on_disk)] })), detail.buildid && SP_JSX.jsxs("div", { children: ["Build: ", detail.buildid] }), SP_JSX.jsxs("div", { children: ["Depots: ", detail.depots?.length ?? 0, " \u00B7 Keys:", " ", detail.key_count ?? 0] }), SP_JSX.jsx("div", { style: {
                                        color: detail.installed ? "#7ee2a8" : "#9aa4b2",
                                    }, children: detail.installed
                                        ? "Installed"
                                        : detail.downloading
                                            ? "Downloading"
                                            : "Not installed" })] }) }) }), SP_JSX.jsxs(DFL.PanelSection, { title: "Integrations", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "SLSonline", description: "Map this game to Spacewar (480) for online features.", checked: detail.slsonline, disabled: busy, onChange: (v) => toggle("SLSonline", () => setSlsonline(detail.app_id, v, detail.fake_appid || "480")) }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "NetSock", description: "Steam Networking Sockets multiplayer patch.", checked: detail.netsock, disabled: busy || notInstalled || !detail.slsonline, onChange: (v) => toggle("NetSock", () => setNetsock(detail.app_id, v)) }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "EOS Proxy", description: "Apply the Epic Online Services proxy.", checked: detail.eos === "active", disabled: busy || notInstalled || !detail.slsonline || !detail.eos_available, onChange: (v) => toggle("EOS Proxy", () => setEos(detail.app_id, v)) }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "EOS + NetSock", description: "Enable the EOS proxy and NetSock together.", checked: detail.eos === "active" && detail.netsock, disabled: busy || notInstalled || !detail.slsonline || !detail.eos_available, onChange: (v) => toggle("EOS + NetSock", () => setEosNetsock(detail.app_id, v)) }) })] }), SP_JSX.jsxs(DFL.PanelSection, { title: "DLC & Depots", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Inject DLCs", description: "Register all DLC AppIDs into AdditionalApps and sync keyed depots.", checked: !!detail.dlcs_injected, disabled: busy, onChange: (v) => toggle("Inject DLCs", () => toggleGameDlcs(detail.app_id, v)) }) }), detail.dlcs_detail && detail.dlcs_detail.length > 0 && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { width: "100%", fontSize: "12px" }, children: [SP_JSX.jsxs("div", { style: { fontWeight: "bold", opacity: 0.85, marginBottom: "6px" }, children: ["DLC AppIDs (", detail.dlcs_detail.length, ")"] }), detail.dlcs_detail.map((dlc) => (SP_JSX.jsxs("div", { style: {
                                            display: "flex",
                                            alignItems: "center",
                                            justifyContent: "space-between",
                                            padding: "4px 0",
                                            borderBottom: "1px solid rgba(255,255,255,0.05)",
                                        }, children: [SP_JSX.jsxs("div", { style: { flex: 1, minWidth: 0, paddingRight: "8px" }, children: [SP_JSX.jsx("span", { style: { fontFamily: "monospace", opacity: 0.75 }, children: dlc.id }), " ", SP_JSX.jsx("span", { children: dlc.name })] }), SP_JSX.jsx("span", { style: {
                                                    fontSize: "10px",
                                                    padding: "2px 6px",
                                                    borderRadius: "4px",
                                                    background: dlc.in_config ? "rgba(126, 226, 168, 0.2)" : "rgba(255, 255, 255, 0.08)",
                                                    color: dlc.in_config ? "#7ee2a8" : "#8a929e",
                                                    whiteSpace: "nowrap",
                                                }, children: dlc.in_config ? "Active in config" : "Not in config" })] }, dlc.id)))] }) })), detail.depots_detail && detail.depots_detail.length > 0 && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { width: "100%", fontSize: "12px" }, children: [SP_JSX.jsxs("div", { style: { fontWeight: "bold", opacity: 0.85, marginBottom: "6px" }, children: ["Depots (", detail.depots_detail.length, ")"] }), detail.depots_detail.map((d) => (SP_JSX.jsxs("div", { style: {
                                            display: "flex",
                                            alignItems: "center",
                                            justifyContent: "space-between",
                                            padding: "5px 0",
                                            borderBottom: "1px solid rgba(255,255,255,0.05)",
                                        }, children: [SP_JSX.jsxs("div", { style: { flex: 1, minWidth: 0, paddingRight: "8px" }, children: [SP_JSX.jsxs("div", { children: [SP_JSX.jsx("b", { style: { fontFamily: "monospace" }, children: d.id }), " ", SP_JSX.jsx("span", { style: { opacity: 0.9 }, children: d.name })] }), SP_JSX.jsxs("div", { style: { fontSize: "10px", opacity: 0.65, marginTop: "2px" }, children: [d.os ? `[${d.os}] ` : "", d.is_dlc ? "[DLC] " : "", d.is_shared ? "[Shared] " : "", d.has_key ? "Key present" : "No key"] })] }), SP_JSX.jsx("span", { style: {
                                                    fontSize: "10px",
                                                    padding: "2px 6px",
                                                    borderRadius: "4px",
                                                    background: d.in_config ? "rgba(126, 226, 168, 0.2)" : "rgba(255, 255, 255, 0.08)",
                                                    color: d.in_config ? "#7ee2a8" : "#8a929e",
                                                    whiteSpace: "nowrap",
                                                }, children: d.in_config ? "Added in config" : "Not in config" })] }, d.id)))] }) }))] }), SP_JSX.jsx(DFL.PanelSection, { children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: () => askUninstall(detail), children: "Uninstall" }) }) }), msg && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: { fontSize: "12px", opacity: 0.85, padding: "8px" }, children: msg }) }))] }));
    }
    // ---- List page ----
    return (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx("style", { children: `
        .uran-game-row {
          display: flex !important;
          align-items: center !important;
          gap: 6px !important;
          width: 100% !important;
          margin-bottom: 8px !important;
        }
        .uran-game-pill {
          min-width: 0 !important;
          flex: 1 1 0% !important;
          height: 38px !important;
          min-height: 38px !important;
          padding: 0 12px !important;
          display: flex !important;
          align-items: center !important;
          justify-content: flex-start !important;
          overflow: hidden !important;
          border-radius: 8px !important;
        }
        .uran-game-pill > div,
        .uran-game-pill > span {
          width: 100% !important;
          min-width: 0 !important;
          overflow: hidden !important;
          text-overflow: ellipsis !important;
          white-space: nowrap !important;
          text-align: left !important;
        }
        .uran-uninstall-btn {
          width: 38px !important;
          min-width: 38px !important;
          max-width: 38px !important;
          height: 38px !important;
          min-height: 38px !important;
          padding: 0 !important;
          flex-shrink: 0 !important;
          display: flex !important;
          align-items: center !important;
          justify-content: center !important;
          border-radius: 8px !important;
        }
        .uran-uninstall-btn:hover,
        .uran-uninstall-btn:focus,
        .uran-uninstall-btn:focus-within {
          color: #ff6b6b !important;
        }
      ` }), SP_JSX.jsx(DFL.PanelSection, { title: `AT0-M Games (${games.length})`, children: loading ? (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: { fontSize: "12px", opacity: 0.7 }, children: "Loading\u2026" }) })) : games.length === 0 ? (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: { fontSize: "12px", opacity: 0.7 }, children: "No AT0-M games registered yet." }) })) : (games.map((g) => (SP_JSX.jsx(DFL.PanelSectionRow, { style: { marginBottom: "6px" }, children: SP_JSX.jsxs(DFL.Focusable, { "flow-children": "horizontal", className: "uran-game-row", children: [SP_JSX.jsx(DFL.DialogButton, { className: "uran-game-pill", onClick: () => openGame(g.app_id), children: SP_JSX.jsx("span", { style: {
                                        overflow: "hidden",
                                        textOverflow: "ellipsis",
                                        whiteSpace: "nowrap",
                                        display: "block",
                                        width: "100%",
                                        fontSize: "13px",
                                    }, children: g.name }) }), SP_JSX.jsx(DFL.DialogButton, { className: "uran-uninstall-btn", disabled: busy, onClick: () => askUninstall(g), children: SP_JSX.jsx(TrashIcon, { size: 16 }) })] }) }, g.app_id)))) }), msg && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: { fontSize: "12px", opacity: 0.85, padding: "8px" }, children: msg }) }))] }));
};
// -- Settings Tab -------------------------------------------------------------
const SettingsTab = () => {
    const [showRestartButton, setShowRestartButton] = SP_REACT.useState(false);
    const [steamStoreEnabled, setSteamStoreEnabled] = SP_REACT.useState(true);
    const [storeStatus, setStoreStatus] = SP_REACT.useState(null);
    const [checkingStore, setCheckingStore] = SP_REACT.useState(false);
    const [manifestIdPinning, setManifestIdPinning] = SP_REACT.useState(false);
    const [notificationMode, setNotificationModeState] = SP_REACT.useState("auto");
    const [msg, setMsg] = SP_REACT.useState("");
    const [stats, setStats] = SP_REACT.useState({ ok: false });
    // -- QR key capture --
    const [keyServer, setKeyServer] = SP_REACT.useState({ running: false, urls: [], status: "idle" });
    const [qrSvg, setQrSvg] = SP_REACT.useState(null);
    const [qrError, setQrError] = SP_REACT.useState("");
    const loadStats = SP_REACT.useCallback(async () => {
        try {
            const s = await getHubcapUserStats();
            if (s)
                setStats(s);
        }
        catch {
            setStats({ ok: false });
        }
    }, []);
    SP_REACT.useEffect(() => {
        let alive = true;
        (async () => {
            try {
                const [srb, mip, nm, storeEnabled, initialStoreStatus] = await Promise.all([
                    getSetting("show_restart_button", false),
                    getSetting("manifestid_pinning", false),
                    getSetting("notification_mode", "auto"),
                    getSetting("steam_store_enabled", true),
                    getStoreDebugStatus(false),
                ]);
                if (!alive)
                    return;
                setShowRestartButton(!!srb);
                setManifestIdPinning(!!mip);
                setSteamStoreEnabled(storeEnabled !== false);
                setStorePatchEnabled(storeEnabled !== false);
                setStoreStatus(initialStoreStatus);
                if (nm)
                    setNotificationModeState(nm);
            }
            catch { }
            loadStats();
        })();
        return () => {
            alive = false;
        };
    }, [loadStats]);
    const refreshStoreStatus = SP_REACT.useCallback(async (force = false) => {
        setCheckingStore(true);
        try {
            setStoreStatus(await getStoreDebugStatus(force));
        }
        catch (e) {
            setStoreStatus((previous) => previous ? {
                ...previous,
                message: `Could not read Steam Store status: ${e}`,
            } : null);
        }
        finally {
            setCheckingStore(false);
        }
    }, []);
    SP_REACT.useEffect(() => {
        const timer = setInterval(() => refreshStoreStatus(false), 10000);
        return () => clearInterval(timer);
    }, [refreshStoreStatus]);
    const changeSteamStoreEnabled = async (enabled) => {
        setSteamStoreEnabled(enabled);
        setStorePatchEnabled(enabled);
        await setSetting("steam_store_enabled", enabled);
    };
    const stopQr = async () => {
        try {
            await stopKeyServer();
        }
        catch { }
        setKeyServer({ running: false, urls: [], status: "idle" });
        setQrSvg(null);
    };
    const startQr = async () => {
        setQrError("");
        setQrSvg(null);
        try {
            const r = await startKeyServer();
            if (!r?.ok) {
                setQrError(r?.error || "Could not start the local server");
                return;
            }
            const url = r.urls?.[0];
            if (!url) {
                setQrError("No network address found. Connect the Deck to Wi-Fi, then try again.");
                return;
            }
            const svg = await browser.toString(url, {
                type: "svg",
                errorCorrectionLevel: "M",
                margin: 1,
                width: 220,
                color: { dark: "#000000", light: "#ffffff" },
            });
            setQrSvg(svg);
            setKeyServer({
                running: true,
                urls: r.urls,
                status: r.status,
                expires_in: r.expires_in,
            });
        }
        catch (e) {
            setQrError(e?.message || "Failed to start");
        }
    };
    // Poll while the capture server is up so the UI flips on its own.
    SP_REACT.useEffect(() => {
        if (!keyServer.running)
            return;
        let alive = true;
        const t = setInterval(async () => {
            try {
                const s = await keyServerStatus();
                if (!alive || !s)
                    return;
                setKeyServer((prev) => ({
                    ...prev,
                    running: s.running,
                    status: s.status,
                    expires_in: s.expires_in,
                }));
                if (!s.running || s.status === "accepted") {
                    clearInterval(t);
                    if (s.status === "accepted") {
                        notify("Uran", "Hubcap key received");
                        setMsg("Key received from your phone");
                        setQrSvg(null);
                        loadStats();
                    }
                }
            }
            catch { }
        }, 1500);
        return () => {
            alive = false;
            clearInterval(t);
        };
    }, [keyServer.running, loadStats]);
    const changeNotificationMode = async (opt) => {
        const val = opt.data;
        setNotificationModeState(val);
        await setSetting("notification_mode", val);
        await setNotificationMode(val);
        await refreshNotificationChannel();
    };
    return (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsxs(DFL.PanelSection, { title: "Hubcap API Key", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Show QR code", description: "Scan with your phone to paste the key \u2014 no keyboard needed.", checked: keyServer.running, onChange: (v) => (v ? startQr() : stopQr()) }) }), keyServer.running && (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: {
                                        display: "flex",
                                        justifyContent: "center",
                                        padding: "8px 0",
                                    }, children: qrSvg ? (SP_JSX.jsx("div", { style: {
                                            background: "#fff",
                                            padding: "10px",
                                            borderRadius: "10px",
                                            lineHeight: 0,
                                        }, dangerouslySetInnerHTML: { __html: qrSvg } })) : (SP_JSX.jsx("div", { style: { opacity: 0.6, fontSize: "12px" }, children: "Generating\u2026" })) }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: {
                                        fontSize: "12px",
                                        textAlign: "center",
                                        color: keyServer.status === "accepted" ? "#7ee2a8" : "#9aa4b2",
                                    }, children: keyServer.status === "accepted"
                                        ? "Key received ✓ — you can close this"
                                        : `Scan with your phone${keyServer.expires_in
                                            ? ` · closes in ${Math.max(0, keyServer.expires_in)}s`
                                            : ""}` }) })] })), qrError && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: { fontSize: "12px", color: "#e57373" }, children: qrError }) })), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { fontSize: "12px", opacity: 0.75, lineHeight: 1.5 }, children: ["The key is shared with ASSella via", " ", SP_JSX.jsx("code", { children: "~/.config/Tachibana Labs/ACCELA.conf" }), "."] }) }), stats.ok && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { fontSize: "12px", lineHeight: 1.7, opacity: 0.9 }, children: [stats.username && (SP_JSX.jsxs("div", { children: ["Account ", SP_JSX.jsx("b", { children: stats.username })] })), stats.requests_remaining != null && (SP_JSX.jsxs("div", { children: ["Requests today: ", stats.daily_usage, "/", stats.daily_limit, " (", stats.requests_remaining, " left)"] })), stats.expires_at && SP_JSX.jsxs("div", { children: ["Key expires: ", stats.expires_at] })] }) })), !stats.ok && stats.error && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: { fontSize: "12px", color: "#e57373" }, children: stats.error }) }))] }), SP_JSX.jsx(DFL.PanelSection, { title: "Notifications", children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.DropdownItem, { label: "Notification channel", rgOptions: NOTIFICATION_MODE_OPTIONS, selectedOption: notificationMode, onChange: changeNotificationMode }) }) }), SP_JSX.jsxs(DFL.PanelSection, { title: "Steam Store", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Steam Store", checked: steamStoreEnabled, onChange: changeSteamStoreEnabled, description: !steamStoreEnabled
                                ? "Store button injection is turned off."
                                : storeStatus?.available
                                    ? `CEF debugging detected on port ${storeStatus.port}. ${storeStatus.store_tab ? "A Store page is open." : "Open a Store page to inspect it."}`
                                    : "CEF debugging is off or unreachable. Steam must expose --cef-enable-debugging for the Store button to work." }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { fontSize: "12px", lineHeight: 1.5, opacity: 0.85 }, children: [storeStatus?.message || "Checking the Steam debugging port…", SP_JSX.jsx("div", { style: { marginTop: "4px", opacity: 0.7 }, children: "Port detection confirms CDP access, but cannot guarantee Valve's current Store layout accepts the button. Recent patch logs are shown below." })] }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: checkingStore, onClick: () => refreshStoreStatus(true), children: checkingStore ? "Checking…" : "Check Steam Store and refresh logs" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { width: "100%", fontSize: "11px", lineHeight: 1.5, maxHeight: "140px", overflowY: "auto", opacity: 0.8 }, children: [SP_JSX.jsx("div", { style: { fontWeight: "bold", marginBottom: "4px" }, children: "Recent Store patch logs" }), storeStatus?.logs?.length ? storeStatus.logs.slice(-12).map((line, index) => (SP_JSX.jsx("div", { style: { overflowWrap: "anywhere" }, children: line }, `${index}-${line}`))) : SP_JSX.jsx("div", { children: "No Store patch messages yet. Keep the feature enabled and open a Store page." }), SP_JSX.jsx("div", { style: { marginTop: "6px", opacity: 0.7 }, children: "For help, share the status above and any log mentioning \u201Csocket\u201D, \u201Cpurchase area\u201D, or \u201Cinjected\u201D." })] }) })] }), SP_JSX.jsxs(DFL.PanelSection, { title: "Injection", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Pin ManifestIds", description: "Write ManifestIds pins for fetched depots.", checked: manifestIdPinning, onChange: (v) => {
                                setManifestIdPinning(v);
                                setSetting("manifestid_pinning", v);
                            } }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Show Exit Steam button", description: "Show a manual Exit Steam button on store pages.", checked: showRestartButton, onChange: (v) => {
                                setShowRestartButton(v);
                                setSetting("show_restart_button", v);
                            } }) })] }), msg && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: { fontSize: "12px", opacity: 0.8, padding: "8px" }, children: msg }) }))] }));
};
// -- Backups Tab --------------------------------------------------------------
const BackupsTab = () => {
    const [backups, setBackups] = SP_REACT.useState([]);
    const [busy, setBusy] = SP_REACT.useState(false);
    const [msg, setMsg] = SP_REACT.useState("");
    const load = async () => {
        setBusy(true);
        try {
            const r = await listBackups();
            setBackups(r ?? []);
        }
        catch { }
        setBusy(false);
    };
    const create = async () => {
        setBusy(true);
        try {
            const r = await createBackup();
            setMsg(`Created backup: ${r}`);
            load();
        }
        catch {
            setMsg("Backup creation failed");
        }
        setBusy(false);
    };
    const restore = async (name) => {
        setBusy(true);
        try {
            const r = await restoreBackup(name);
            if (r?.error) {
                setMsg(`Error: ${r.error}`);
                notify("Uran", `Restore failed: ${r.error}`);
            }
            else {
                const text = r?.verified
                    ? `Restored config from ${name}`
                    : `Restored (unverified): ${name}`;
                setMsg(text);
                notify("Uran", text);
                await load();
            }
        }
        catch (e) {
            setMsg(`Error: ${e}`);
        }
        setBusy(false);
    };
    SP_REACT.useEffect(() => {
        load();
    }, []);
    return (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: create, children: "Create Backup Now" }) }), SP_JSX.jsxs(DFL.PanelSection, { title: `Backups (${backups.length})`, children: [backups.length === 0 && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: { opacity: 0.6, padding: "8px" }, children: "None" }) })), backups.map((b) => {
                        const isPreRestore = b.stamp.startsWith("pre_restore.");
                        const rawTs = isPreRestore
                            ? b.stamp.slice("pre_restore.".length)
                            : b.stamp.replace("sls.", "");
                        const dateMatch = rawTs.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/);
                        const displayTs = dateMatch
                            ? `${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]} ${dateMatch[4]}:${dateMatch[5]}`
                            : rawTs;
                        const label = isPreRestore ? `Pre-restore · ${displayTs}` : displayTs;
                        return (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { onClick: () => restore(b.name), layout: "below", children: SP_JSX.jsxs("div", { style: {
                                        display: "flex",
                                        justifyContent: "space-between",
                                        alignItems: "center",
                                        width: "100%",
                                    }, children: [SP_JSX.jsx("span", { style: { fontSize: "13px" }, children: label }), SP_JSX.jsxs("span", { style: {
                                                fontSize: "11px",
                                                color: "#888",
                                                marginLeft: "8px",
                                            }, children: [Math.round(b.size / 1024), " KB"] })] }) }) }, b.name));
                    })] }), msg && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: { fontSize: "12px", opacity: 0.8, padding: "8px" }, children: msg }) }))] }));
};
// -- Depot Keys Tab ------------------------------------------------------------
// -- Plugin Entry -------------------------------------------------------------
let lastActiveTab = "search";
var index = definePlugin(() => {
    const storePatchCleanup = initStorePatch();
    const contextMenuCleanup = initContextMenuPatch();
    getSetting("notification_mode", "auto")
        .then((v) => {
        setNotificationMode(v);
        return refreshNotificationChannel();
    })
        .catch(() => { });
    const Content = () => {
        const [activeTab, setActiveTab] = SP_REACT.useState(lastActiveTab);
        const selectTab = (tab) => {
            lastActiveTab = tab;
            setActiveTab(tab);
        };
        const tabStyle = (active) => ({
            flex: 1,
            textAlign: "center",
            padding: "8px 4px",
            cursor: "pointer",
            fontSize: "13px",
            fontWeight: active ? 700 : 400,
            color: active ? "#fff" : "#999",
            background: active ? "rgba(255,255,255,0.08)" : "transparent",
            borderRadius: "6px",
            border: active
                ? "1px solid rgba(255,255,255,0.15)"
                : "1px solid transparent",
            transition: "background 0.15s, border-color 0.15s, color 0.15s",
            userSelect: "none",
            WebkitUserSelect: "none",
            outline: "none",
        });
        const focusClass = "assella-tab-focus";
        const activeFocusClass = "assella-tab-active-focus";
        return (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx("style", { children: `
          .${focusClass}{background:rgba(255,255,255,0.12) !important;color:#ddd !important;border-color:rgba(255,255,255,0.25) !important}
          .${activeFocusClass}{background:rgba(255,255,255,0.18) !important;color:#fff !important;border-color:rgba(255,255,255,0.35) !important}
        ` }), SP_JSX.jsxs(DFL.Focusable, { "flow-children": "horizontal", style: { display: "flex", gap: "4px", padding: "0 0 12px 0" }, children: [SP_JSX.jsx(DFL.Focusable, { focusClassName: activeTab === "search" ? activeFocusClass : focusClass, onActivate: () => selectTab("search"), style: tabStyle(activeTab === "search"), children: "Search" }), SP_JSX.jsx(DFL.Focusable, { focusClassName: activeTab === "atom" ? activeFocusClass : focusClass, onActivate: () => selectTab("atom"), style: tabStyle(activeTab === "atom"), children: "AT0-M" }), SP_JSX.jsx(DFL.Focusable, { focusClassName: activeTab === "settings" ? activeFocusClass : focusClass, onActivate: () => selectTab("settings"), style: tabStyle(activeTab === "settings"), children: "Settings" }), SP_JSX.jsx(DFL.Focusable, { focusClassName: activeTab === "backups" ? activeFocusClass : focusClass, onActivate: () => selectTab("backups"), style: tabStyle(activeTab === "backups"), children: "Backups" })] }), activeTab === "search" && SP_JSX.jsx(SearchTab, {}), activeTab === "atom" && SP_JSX.jsx(AtomGamesTab, {}), activeTab === "backups" && SP_JSX.jsx(BackupsTab, {}), activeTab === "settings" && SP_JSX.jsx(SettingsTab, {})] }));
    };
    return {
        name: "ASSella",
        content: SP_JSX.jsx(Content, {}),
        icon: (SP_JSX.jsx("div", { style: { display: "flex", alignItems: "center", justifyContent: "center" }, children: SP_JSX.jsx(AssellaLogo, { size: "20px" }) })),
        onDismount() {
            storePatchCleanup();
            contextMenuCleanup();
        },
    };
});

export { index as default };
//# sourceMappingURL=index.js.map
