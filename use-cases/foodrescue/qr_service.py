"""FoodRescue AI — Pure-Python QR Code Generation & Verification Engine.

Provides:
1. Cryptographically secure handover verification token generator.
2. Zero-dependency ISO/IEC 18004 QR code matrix encoder (Byte Mode, ECC Level M).
3. Pure-Python PNG image stream encoder with standard library zlib compression.
4. Scalable SVG vector generator for browser rendering.
5. Handover payload packaging and verification helpers for FoodRescue AI tasks.
"""

import os
import zlib
import struct
import secrets
import hashlib
import logging
from typing import List, Tuple, Optional, Dict, Any

logger = logging.getLogger("foodrescue.qr")

# QR Code GF(256) Math & Reed-Solomon Tables
GF_EXP = [0] * 512
GF_LOG = [0] * 256

def _init_galois_field():
    x = 1
    for i in range(255):
        GF_EXP[i] = x
        GF_EXP[i + 255] = x
        GF_LOG[x] = i
        x = (x << 1) ^ (0x11D if (x & 0x80) else 0)
    GF_LOG[0] = 0

_init_galois_field()

def _gf_mul(x: int, y: int) -> int:
    if x == 0 or y == 0:
        return 0
    return GF_EXP[GF_LOG[x] + GF_LOG[y]]

def _rs_generator_poly(ec_count: int) -> List[int]:
    poly = [1]
    for i in range(ec_count):
        factor = [1, GF_EXP[i]]
        new_poly = [0] * (len(poly) + len(factor) - 1)
        for j, c1 in enumerate(poly):
            for k, c2 in enumerate(factor):
                new_poly[j + k] ^= _gf_mul(c1, c2)
        poly = new_poly
    return poly

def _rs_encode(data: List[int], ec_count: int) -> List[int]:
    gen = _rs_generator_poly(ec_count)
    res = list(data) + [0] * ec_count
    for i in range(len(data)):
        lead = res[i]
        if lead != 0:
            for j, g in enumerate(gen):
                res[i + j] ^= _gf_mul(g, lead)
    return res[len(data):]

# Standard QR Version Parameters (Version 1 to 10 for ECC Level M)
# Format: (version, total_codewords, ec_codewords_per_block, num_blocks)
QR_VERSION_SPECS_M = {
    1: (1, 26, 10, 1),    # Cap: 14 bytes
    2: (2, 44, 16, 1),    # Cap: 26 bytes
    3: (3, 70, 26, 1),    # Cap: 42 bytes
    4: (4, 100, 18, 2),   # Cap: 62 bytes (64 data bytes total)
    5: (5, 134, 24, 2),   # Cap: 84 bytes
    6: (6, 172, 16, 4),   # Cap: 106 bytes
    7: (7, 196, 18, 4),   # Cap: 122 bytes
    8: (8, 242, 22, 4),   # Cap: 152 bytes
    9: (9, 292, 22, 5),   # Cap: 180 bytes
    10: (10, 346, 26, 5), # Cap: 213 bytes
}

# Alignment Pattern Locations per Version
ALIGNMENT_LOCATIONS = {
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}


class PureQRCode:
    """Pure-Python standard QR Code matrix builder."""

    def __init__(self, text: str):
        self.text = text
        self.raw_bytes = text.encode("utf-8")
        self.version, self.total_cw, self.ec_per_block, self.num_blocks = self._determine_version(len(self.raw_bytes))
        self.size = 17 + 4 * self.version
        self.modules = [[None for _ in range(self.size)] for _ in range(self.size)]
        self.is_function = [[False for _ in range(self.size)] for _ in range(self.size)]
        self._build()

    def _determine_version(self, data_len: int) -> Tuple[int, int, int, int]:
        for ver, (v, total_cw, ec_cw, blocks) in QR_VERSION_SPECS_M.items():
            data_cap = total_cw - (ec_cw * blocks)
            # Byte mode header: 4 bits mode + 8 bits length indicator = 12 bits -> 1.5 bytes + 1 pad
            if data_len + 3 <= data_cap:
                return (v, total_cw, ec_cw, blocks)
        return (10, 346, 26, 5)

    def _build(self):
        self._place_finder_patterns()
        self._place_alignment_patterns()
        self._place_timing_patterns()
        self._place_dark_module()
        self._reserve_format_areas()
        
        data_bits = self._encode_data_bits()
        self._place_data_bits(data_bits)
        self._apply_best_mask()

    def _set_module(self, r: int, c: int, val: bool, is_fn: bool = False):
        if 0 <= r < self.size and 0 <= c < self.size:
            self.modules[r][c] = val
            if is_fn:
                self.is_function[r][c] = True

    def _place_finder_patterns(self):
        positions = [(0, 0), (0, self.size - 7), (self.size - 7, 0)]
        for r_orig, c_orig in positions:
            for r in range(7):
                for c in range(7):
                    is_black = (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4))
                    self._set_module(r_orig + r, c_orig + c, is_black, True)
            # Separators
            for r in range(-1, 8):
                for c in range(-1, 8):
                    rr, cc = r_orig + r, c_orig + c
                    if 0 <= rr < self.size and 0 <= cc < self.size and (r in (-1, 7) or c in (-1, 7)):
                        self._set_module(rr, cc, False, True)

    def _place_alignment_patterns(self):
        if self.version < 2:
            return
        locs = ALIGNMENT_LOCATIONS.get(self.version, [])
        for r_center in locs:
            for c_center in locs:
                # Skip finders
                if (r_center < 9 and c_center < 9) or (r_center < 9 and c_center > self.size - 10) or (r_center > self.size - 10 and c_center < 9):
                    continue
                for r in range(-2, 3):
                    for c in range(-2, 3):
                        val = (abs(r) == 2 or abs(c) == 2 or (r == 0 and c == 0))
                        self._set_module(r_center + r, c_center + c, val, True)

    def _place_timing_patterns(self):
        for i in range(8, self.size - 8):
            val = (i % 2 == 0)
            if not self.is_function[6][i]:
                self._set_module(6, i, val, True)
            if not self.is_function[i][6]:
                self._set_module(i, 6, val, True)

    def _place_dark_module(self):
        self._set_module(4 * self.version + 9, 8, True, True)

    def _reserve_format_areas(self):
        for i in range(9):
            if not self.is_function[8][i]:
                self._set_module(8, i, False, True)
            if not self.is_function[i][8]:
                self._set_module(i, 8, False, True)
        for i in range(self.size - 8, self.size):
            if not self.is_function[8][i]:
                self._set_module(8, i, False, True)
            if not self.is_function[i][8]:
                self._set_module(i, 8, False, True)

    def _encode_data_bits(self) -> List[int]:
        # 1. Byte mode indicator: 0100
        bits = [0, 1, 0, 0]
        # 2. Character count indicator (8 bits for versions 1-9, 16 bits for ver 10)
        length_bits = 8 if self.version < 10 else 16
        length_val = len(self.raw_bytes)
        for b in range(length_bits - 1, -1, -1):
            bits.append((length_val >> b) & 1)
        # 3. Data bytes
        for byte_val in self.raw_bytes:
            for b in range(7, -1, -1):
                bits.append((byte_val >> b) & 1)
        
        # 4. Terminator (up to 4 zeroes)
        total_data_cw = self.total_cw - (self.ec_per_block * self.num_blocks)
        total_data_bits = total_data_cw * 8
        terminator_len = min(4, total_data_bits - len(bits))
        bits.extend([0] * max(0, terminator_len))
        
        # 5. Pad to multiple of 8
        while len(bits) % 8 != 0:
            bits.append(0)
            
        # Convert bits to bytes
        cw_data = []
        for i in range(0, len(bits), 8):
            val = 0
            for j in range(8):
                val = (val << 1) | bits[i + j]
            cw_data.append(val)
            
        # 6. Pad with alternating bytes 236 (0xEC) and 17 (0x11)
        pad_bytes = [0xEC, 0x11]
        pad_idx = 0
        while len(cw_data) < total_data_cw:
            cw_data.append(pad_bytes[pad_idx % 2])
            pad_idx += 1

        # 7. Block partition & Reed-Solomon Error Correction
        data_blocks = []
        ec_blocks = []
        base_block_size = total_data_cw // self.num_blocks
        extra_blocks = total_data_cw % self.num_blocks
        
        offset = 0
        for b in range(self.num_blocks):
            blk_size = base_block_size + (1 if b >= self.num_blocks - extra_blocks else 0)
            blk_data = cw_data[offset : offset + blk_size]
            data_blocks.append(blk_data)
            ec_blocks.append(_rs_encode(blk_data, self.ec_per_block))
            offset += blk_size

        # 8. Interleave Data & EC codewords
        final_cw = []
        max_data_len = max(len(b) for b in data_blocks)
        for i in range(max_data_len):
            for blk in data_blocks:
                if i < len(blk):
                    final_cw.append(blk[i])
        for i in range(self.ec_per_block):
            for blk in ec_blocks:
                final_cw.append(blk[i])

        # Convert final codewords to bit stream
        final_bits = []
        for cw in final_cw:
            for b in range(7, -1, -1):
                final_bits.append((cw >> b) & 1)
        return final_bits

    def _place_data_bits(self, bits: List[int]):
        bit_idx = 0
        up = True
        c = self.size - 1
        while c > 0:
            if c == 6:  # Skip vertical timing column
                c -= 1
            rows = range(self.size - 1, -1, -1) if up else range(self.size)
            for r in rows:
                for col in (c, c - 1):
                    if not self.is_function[r][col]:
                        val = bits[bit_idx] if bit_idx < len(bits) else 0
                        self.modules[r][col] = bool(val)
                        bit_idx += 1
            c -= 2
            up = not up

    def _apply_best_mask(self):
        # Format info for ECC Level M (Mask pattern 0): BCH code 0x5372 ^ 0x5412 = 0x0760
        mask_format = 0x5372 ^ 0x5412  # Standard precalculated Level M mask 0
        
        # Apply mask 0 to non-function modules
        for r in range(self.size):
            for c in range(self.size):
                if not self.is_function[r][c]:
                    if (r + c) % 2 == 0:
                        self.modules[r][c] = not self.modules[r][c]

        # Write 15-bit format info
        format_bits = [(mask_format >> i) & 1 for i in range(15)]
        
        # Top-left horizontal & vertical
        for i in range(6):
            self.modules[8][i] = bool(format_bits[i])
        self.modules[8][7] = bool(format_bits[6])
        self.modules[8][8] = bool(format_bits[7])
        self.modules[7][8] = bool(format_bits[8])
        for i in range(9, 15):
            self.modules[14 - i][8] = bool(format_bits[i])

        # Bottom-left and Top-right
        for i in range(7):
            self.modules[self.size - 1 - i][8] = bool(format_bits[i])
        for i in range(8):
            self.modules[8][self.size - 8 + i] = bool(format_bits[7 + i])


def generate_qr_matrix(text: str) -> List[List[bool]]:
    """Generate 2D boolean module matrix for the given text."""
    qr = PureQRCode(text)
    return [[bool(cell) for cell in row] for row in qr.modules]


def generate_qr_png_bytes(text: str, box_size: int = 10, border: int = 4) -> bytes:
    """Generate a valid binary PNG image (bytes) for the given QR content with zero third-party dependencies."""
    matrix = generate_qr_matrix(text)
    qr_size = len(matrix)
    img_size = (qr_size + 2 * border) * box_size

    # Build raw RGBA image buffer (row-by-row with PNG filter type byte 0)
    raw_scanlines = bytearray()
    black_pixel = b"\x10\x18\x27\xFF"  # High-contrast dark navy (#101827)
    white_pixel = b"\xFF\xFF\xFF\xFF"  # Crisp pure white background

    for y in range(img_size):
        raw_scanlines.append(0)  # Filter type 0 (None)
        qr_y = (y // box_size) - border
        for x in range(img_size):
            qr_x = (x // box_size) - border
            if 0 <= qr_y < qr_size and 0 <= qr_x < qr_size and matrix[qr_y][qr_x]:
                raw_scanlines.extend(black_pixel)
            else:
                raw_scanlines.extend(white_pixel)

    # Compress scanlines with zlib
    compressed_idat = zlib.compress(bytes(raw_scanlines), level=9)

    # Assemble standard PNG Chunks: Signature, IHDR, IDAT, IEND
    png_signature = b"\x89PNG\r\n\x1a\n"
    
    def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        return length + chunk_type + data + crc

    # IHDR: width(4), height(4), bit_depth(1=8), color_type(1=6:RGBA), compression(1=0), filter(1=0), interlace(1=0)
    ihdr_data = struct.pack(">IIBBBBB", img_size, img_size, 8, 6, 0, 0, 0)
    ihdr_chunk = make_chunk(b"IHDR", ihdr_data)
    idat_chunk = make_chunk(b"IDAT", compressed_idat)
    iend_chunk = make_chunk(b"IEND", b"")

    return png_signature + ihdr_chunk + idat_chunk + iend_chunk


def generate_qr_svg(text: str, box_size: int = 10, border: int = 4) -> str:
    """Generate scalable vector SVG string for browser display."""
    matrix = generate_qr_matrix(text)
    qr_size = len(matrix)
    img_size = (qr_size + 2 * border) * box_size

    rects = []
    for r in range(qr_size):
        for c in range(qr_size):
            if matrix[r][c]:
                x = (c + border) * box_size
                y = (r + border) * box_size
                rects.append(f'<rect x="{x}" y="{y}" width="{box_size}" height="{box_size}" fill="#0f172a" />')

    svg_content = "\n  ".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {img_size} {img_size}" width="100%" height="100%" shape-rendering="crispEdges">\n'
        f'  <rect width="100%" height="100%" fill="#ffffff" />\n'
        f'  {svg_content}\n'
        f'</svg>'
    )


# =============================================================================
# SECURE HANDOVER VERIFICATION HELPERS
# =============================================================================

def generate_secure_token(prefix: str = "PK") -> str:
    """Generate cryptographically secure random token for physical QR handover."""
    clean_prefix = prefix.upper().strip()
    rand_hex = secrets.token_hex(12)
    return f"FR-{clean_prefix}-{rand_hex}"


def hash_token(token: str) -> str:
    """Hash token using SHA-256 for secure storage."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def get_base_url() -> str:
    """Retrieve production or development base domain for verification URLs."""
    custom = os.environ.get("VERIFICATION_BASE_URL") or os.environ.get("FOODRESCUE_BASE_URL")
    if custom:
        return custom.rstrip("/")
    vercel = os.environ.get("VERCEL_URL")
    if vercel:
        return f"https://{vercel.rstrip('/')}"
    return "https://foodrescue-ai-ten.vercel.app"


def build_verification_url(qr_type: str, token: str, base_url: Optional[str] = None) -> str:
    """Construct standard mobile camera verification URL."""
    root = (base_url or get_base_url()).rstrip("/")
    type_slug = "pickup" if qr_type.upper() == "PICKUP" else "delivery"
    return f"{root}/verify/{type_slug}/{token}"
