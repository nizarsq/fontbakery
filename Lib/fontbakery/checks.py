#!/usr/bin/env python2
# Copyright 2016 The Fontbakery Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
from __future__ import print_function
import os
import sys
import tempfile
import logging
import requests
import urllib
import csv
import re
import defusedxml.lxml
from fontTools import ttLib
from unidecode import unidecode
import plistlib
from fontbakery.pifont import PiFont
from fontbakery.utils import (
                             get_name_string,
                             check_bit_entry,
                             ttfauto_fpgm_xheight_rounding,
                             glyphs_surface_area,
                             save_FamilyProto_Message,
                             assertExists
                             )
from fontbakery.constants import (
                                 IMPORTANT,
                                 CRITICAL,
                                 STYLE_NAMES,
                                 NAMEID_FONT_FAMILY_NAME,
                                 NAMEID_FONT_SUBFAMILY_NAME,
                                 NAMEID_FULL_FONT_NAME,
                                 NAMEID_VERSION_STRING,
                                 NAMEID_POSTSCRIPT_NAME,
                                 NAMEID_MANUFACTURER_NAME,
                                 NAMEID_DESCRIPTION,
                                 NAMEID_LICENSE_DESCRIPTION,
                                 NAMEID_LICENSE_INFO_URL,
                                 NAMEID_TYPOGRAPHIC_FAMILY_NAME,
                                 NAMEID_TYPOGRAPHIC_SUBFAMILY_NAME,
                                 NAMEID_STR,
                                 RIBBI_STYLE_NAMES,
                                 PLATFORM_ID_MACINTOSH,
                                 PLATFORM_ID_WINDOWS,
                                 PLATID_STR,
                                 WEIGHT_VALUE_TO_NAME,
                                 FSSEL_ITALIC,
                                 FSSEL_BOLD,
                                 FSSEL_REGULAR,
                                 MACSTYLE_BOLD,
                                 MACSTYLE_ITALIC,
                                 PANOSE_PROPORTION_ANY,
                                 PANOSE_PROPORTION_MONOSPACED,
                                 IS_FIXED_WIDTH_NOT_MONOSPACED,
                                 IS_FIXED_WIDTH_MONOSPACED,
                                 LANG_ID_ENGLISH_USA,
                                 PLACEHOLDER_LICENSING_TEXT,
                                 LICENSE_URL,
                                 LICENSE_NAME,
                                 REQUIRED_TABLES,
                                 OPTIONAL_TABLES,
                                 UNWANTED_TABLES,
                                 WHITESPACE_CHARACTERS,
                                 PLAT_ENC_ID_UCS2
                                 )
try:
  import fontforge  #pylint: disable=unused-import
except ImportError:
  logging.warning("fontforge python module is not available!"
                  " To install it, see"
                  " https://github.com/googlefonts/"
                  "gf-docs/blob/master/ProjectChecklist.md#fontforge")
  pass

# =======================================================================
# The following functions implement each of the individual checks per-se.
# =======================================================================


def check_file_is_named_canonically(fb, font_fname):
  """A font's filename must be composed in the following manner:

  <familyname>-<stylename>.ttf

  e.g Nunito-Regular.ttf, Oswald-BoldItalic.ttf"""
  fb.new_check("001", "Checking file is named canonically")
  fb.set_priority(CRITICAL)

  file_path, filename = os.path.split(font_fname)
  basename = os.path.splitext(filename)[0]
  # remove spaces in style names
  style_file_names = [name.replace(' ', '') for name in STYLE_NAMES]
  if '-' in basename and basename.split('-')[1] in style_file_names:
    fb.ok("{} is named canonically".format(font_fname))
    return True
  else:
    fb.error(('Style name used in "{}" is not canonical.'
              ' You should rebuild the font using'
              ' any of the following'
              ' style names: "{}".').format(font_fname,
                                            '", "'.join(STYLE_NAMES)))
    return False


def perform_all_fontforge_checks(fb, validation_state):
  def ff_check(description, condition, err_msg, ok_msg):
    import sha
    m = sha.new()
    m.update(description)
    short_hash = m.hexdigest()[:8]
    fb.new_check("039-{}".format(short_hash),
                 "fontforge-check: {}".format(description))
    if condition is False:
      fb.error("fontforge-check: {}".format(err_msg))
    else:
      fb.ok("fontforge-check: {}".format(ok_msg))

  ff_check("Contours are closed?",
           bool(validation_state & 0x2) is False,
           "Contours are not closed!",
           "Contours are closed.")

  ff_check("Contours do not intersect",
           bool(validation_state & 0x4) is False,
           "There are countour intersections!",
           "Contours do not intersect.")

  ff_check("Contours have correct directions",
           bool(validation_state & 0x8) is False,
           "Contours have incorrect directions!",
           "Contours have correct directions.")

  ff_check("References in the glyph haven't been flipped",
           bool(validation_state & 0x10) is False,
           "References in the glyph have been flipped!",
           "References in the glyph haven't been flipped.")

  ff_check("Glyphs have points at extremas",
           bool(validation_state & 0x20) is False,
           "Glyphs do not have points at extremas!",
           "Glyphs have points at extremas.")

  ff_check("Glyph names referred to from glyphs present in the font",
           bool(validation_state & 0x40) is False,
           "Glyph names referred to from glyphs"
           " not present in the font!",
           "Glyph names referred to from glyphs"
           " present in the font.")

  ff_check("Points (or control points) are not too far apart",
           bool(validation_state & 0x40000) is False,
           "Points (or control points) are too far apart!",
           "Points (or control points) are not too far apart.")

  ff_check("Not more than 1,500 points in any glyph"
           " (a PostScript limit)",
           bool(validation_state & 0x80) is False,
           "There are glyphs with more than 1,500 points!"
           "Exceeds a PostScript limit.",
           "Not more than 1,500 points in any glyph"
           " (a PostScript limit).")

  ff_check("PostScript has a limit of 96 hints in glyphs",
           bool(validation_state & 0x100) is False,
           "Exceeds PostScript limit of 96 hints per glyph",
           "Font respects PostScript limit of 96 hints per glyph")

  ff_check("Font doesn't have invalid glyph names",
           bool(validation_state & 0x200) is False,
           "Font has invalid glyph names!",
           "Font doesn't have invalid glyph names.")

  ff_check("Glyphs have allowed numbers of points defined in maxp",
           bool(validation_state & 0x400) is False,
           "Glyphs exceed allowed numbers of points defined in maxp",
           "Glyphs have allowed numbers of points defined in maxp.")

  ff_check("Glyphs have allowed numbers of paths defined in maxp",
           bool(validation_state & 0x800) is False,
           "Glyphs exceed allowed numbers of paths defined in maxp!",
           "Glyphs have allowed numbers of paths defined in maxp.")

  ff_check("Composite glyphs have allowed numbers"
           " of points defined in maxp?",
           bool(validation_state & 0x1000) is False,
           "Composite glyphs exceed allowed numbers"
           " of points defined in maxp!",
           "Composite glyphs have allowed numbers"
           " of points defined in maxp.")

  ff_check("Composite glyphs have allowed numbers"
           " of paths defined in maxp",
           bool(validation_state & 0x2000) is False,
           "Composite glyphs exceed"
           " allowed numbers of paths defined in maxp!",
           "Composite glyphs have"
           " allowed numbers of paths defined in maxp.")

  ff_check("Glyphs instructions have valid lengths",
           bool(validation_state & 0x4000) is False,
           "Glyphs instructions have invalid lengths!",
           "Glyphs instructions have valid lengths.")

  ff_check("Points in glyphs are integer aligned",
           bool(validation_state & 0x80000) is False,
           "Points in glyphs are not integer aligned!",
           "Points in glyphs are integer aligned.")

  # According to the opentype spec, if a glyph contains an anchor point
  # for one anchor class in a subtable, it must contain anchor points
  # for all anchor classes in the subtable. Even it, logically,
  # they do not apply and are unnecessary.
  ff_check("Glyphs have all required anchors.",
           bool(validation_state & 0x100000) is False,
           "Glyphs do not have all required anchors!",
           "Glyphs have all required anchors.")

  ff_check("Glyph names are unique?",
           bool(validation_state & 0x200000) is False,
           "Glyph names are not unique!",
           "Glyph names are unique.")

  ff_check("Unicode code points are unique?",
           bool(validation_state & 0x400000) is False,
           "Unicode code points are not unique!",
           "Unicode code points are unique.")

  ff_check("Do hints overlap?",
           bool(validation_state & 0x800000) is False,
           "Hints should NOT overlap!",
           "Hinds do not overlap.")


def check_nonligated_sequences_kerning_info(fb, font, has_kerning_info):
  ''' Fonts with ligatures should have kerning on the corresponding
      non-ligated sequences for text where ligatures aren't used.
  '''
  fb.new_check("065", "Is there kerning info for non-ligated sequences?")
  if has_kerning_info is False:
    fb.skip("This font lacks kerning info.")
  else:
    all_ligatures = get_all_ligatures(font)

    def look_for_nonligated_kern_info(table):
      for pairpos in table.SubTable:
        for i, glyph in enumerate(pairpos.Coverage.glyphs):
          if glyph in all_ligatures.keys():
            try:
              for pairvalue in pairpos.PairSet[i].PairValueRecord:
                if pairvalue.SecondGlyph in all_ligatures[glyph]:
                  del all_ligatures[glyph]
            except:
              # Sometimes for unknown reason an exception
              # is raised for accessing pairpos.PairSet
              pass

    for lookup in font["GPOS"].table.LookupList.Lookup:
      if lookup.LookupType == 2:  # type 2 = Pair Adjustment
        look_for_nonligated_kern_info(lookup)
      # elif lookup.LookupType == 9:
      #   if lookup.SubTable[0].ExtensionLookupType == 2:
      #     look_for_nonligated_kern_info(lookup.SubTable[0])

    def ligatures_str(ligatures):
      result = []
      for first in ligatures:
        result.extend(["{}_{}".format(first, second)
                       for second in ligatures[first]])
      return result

    if all_ligatures != {}:
      fb.error(("GPOS table lacks kerning info for the following"
                " non-ligated sequences: "
                "{}").format(ligatures_str(all_ligatures)))
    else:
      fb.ok("GPOS table provides kerning info for "
            "all non-ligated sequences.")


def check_there_is_no_KERN_table_in_the_font(fb, font):
  """Fonts should have their kerning implemented in the GPOS table"""
  fb.new_check("066", "Is there a 'KERN' table declared in the font?")
  try:
    font["KERN"]
    fb.error("Font should not have a 'KERN' table")
  except KeyError:
    fb.ok("Font does not declare a 'KERN' table.")


def check_familyname_does_not_begin_with_a_digit(fb, font):
  """Font family names which start with a numeral are often not
  discoverable in Windows applications."""
  fb.new_check("067", "Make sure family name"
                      " does not begin with a digit.")

  failed = False
  for name in get_name_string(font, NAMEID_FONT_FAMILY_NAME):
    digits = map(str, range(0, 10))
    if name[0] in digits:
      fb.error(("Font family name '{}'"
                " begins with a digit!").format(name))
      failed = True
  if failed is False:
    fb.ok("Font family name first character is not a digit.")


def check_fullfontname_begins_with_the_font_familyname(fb, font):
  fb.new_check("068", "Does full font name begin with the font family name?")
  familyname = get_name_string(font, NAMEID_FONT_FAMILY_NAME)
  fullfontname = get_name_string(font, NAMEID_FULL_FONT_NAME)

  if len(familyname) == 0:
    fb.error('Font lacks a NAMEID_FONT_FAMILY_NAME entry'
             ' in the name table.')
  elif len(fullfontname) == 0:
    fb.error('Font lacks a NAMEID_FULL_FONT_NAME entry'
             ' in the name table.')
  else:
    # we probably should check all found values are equivalent.
    # and, in that case, then performing the rest of the check
    # with only the first occurences of the name entries
    # will suffice:
    fullfontname = fullfontname[0]
    familyname = familyname[0]

    if not fullfontname.startswith(familyname):
      fb.error(" On the NAME table, the full font name"
               " (NameID {} - FULL_FONT_NAME: '{}')"
               " does not begin with font family name"
               " (NameID {} - FONT_FAMILY_NAME:"
               " '{}')".format(NAMEID_FULL_FONT_NAME,
                               familyname,
                               NAMEID_FONT_FAMILY_NAME,
                               fullfontname))
    else:
      fb.ok('Full font name begins with the font family name.')


def check_unused_data_at_the_end_of_glyf_table(fb, font):
  fb.new_check("069", "Is there any unused data at the end of the glyf table?")
  if 'CFF ' in font:
    fb.skip("This check does not support CFF fonts.")
  else:
    # -1 because https://www.microsoft.com/typography/otspec/loca.htm
    expected = len(font['loca']) - 1
    actual = len(font['glyf'])
    diff = actual - expected

    # allow up to 3 bytes of padding
    if diff > 3:
      fb.error(("Glyf table has unreachable data at"
                " the end of the table."
                " Expected glyf table length {}"
                " (from loca table), got length"
                " {} (difference: {})").format(expected, actual, diff))
    elif diff < 0:
      fb.error(("Loca table references data beyond"
                " the end of the glyf table."
                " Expected glyf table length {}"
                " (from loca table), got length"
                " {} (difference: {})").format(expected, actual, diff))
    else:
      fb.ok("There is no unused data at"
            " the end of the glyf table.")


def check_font_has_EURO_SIGN_character(fb, font):
  fb.new_check("070", "Font has 'EURO SIGN' character?")

  def font_has_char(font, c):
    if c in font['cmap'].buildReversed():
      return len(font['cmap'].buildReversed()[c]) > 0
    else:
      return False

  if font_has_char(font, 'Euro'):
    fb.ok("Font has 'EURO SIGN' character.")
  else:
    fb.error("Font lacks the '%s' character." % 'EURO SIGN')


def check_font_follows_the_family_naming_recommendations(fb, font):
  fb.new_check("071", "Font follows the family naming recommendations?")
  # See http://forum.fontlab.com/index.php?topic=313.0
  bad_entries = []

  # <Postscript name> may contain only a-zA-Z0-9
  # and one hyphen
  regex = re.compile(r'[a-z0-9-]+', re.IGNORECASE)
  for name in get_name_string(font, NAMEID_POSTSCRIPT_NAME):
    if not regex.match(name):
      bad_entries.append({'field': 'PostScript Name',
                          'rec': 'May contain only a-zA-Z0-9'
                                 ' characters and an hyphen'})
    if name.count('-') > 1:
      bad_entries.append({'field': 'Postscript Name',
                          'rec': 'May contain not more'
                                 ' than a single hyphen'})

  for name in get_name_string(font, NAMEID_FULL_FONT_NAME):
    if len(name) >= 64:
      bad_entries.append({'field': 'Full Font Name',
                          'rec': 'exceeds max length (64)'})

  for name in get_name_string(font, NAMEID_POSTSCRIPT_NAME):
    if len(name) >= 30:
      bad_entries.append({'field': 'PostScript Name',
                          'rec': 'exceeds max length (30)'})

  for name in get_name_string(font, NAMEID_FONT_FAMILY_NAME):
    if len(name) >= 32:
      bad_entries.append({'field': 'Family Name',
                          'rec': 'exceeds max length (32)'})

  for name in get_name_string(font, NAMEID_FONT_SUBFAMILY_NAME):
    if len(name) >= 32:
      bad_entries.append({'field': 'Style Name',
                          'rec': 'exceeds max length (32)'})

  for name in get_name_string(font, NAMEID_TYPOGRAPHIC_FAMILY_NAME):
    if len(name) >= 32:
      bad_entries.append({'field': 'OT Family Name',
                          'rec': 'exceeds max length (32)'})

  for name in get_name_string(font, NAMEID_TYPOGRAPHIC_SUBFAMILY_NAME):
    if len(name) >= 32:
      bad_entries.append({'field': 'OT Style Name',
                          'rec': 'exceeds max length (32)'})
  weight_value = None
  if 'OS/2' in font:
    field = 'OS/2 usWeightClass'
    weight_value = font['OS/2'].usWeightClass
  if 'CFF' in font:
    field = 'CFF Weight'
    weight_value = font['CFF'].Weight

  if weight_value is not None:
    # <Weight> value >= 250 and <= 900 in steps of 50
    if weight_value % 50 != 0:
      bad_entries.append({"field": field,
                          "rec": "Value should idealy be a multiple of 50."})
    full_info = " "
    " 'Having a weightclass of 100 or 200 can result in a \"smear bold\" or"
    " (unintentionally) returning the style-linked bold. Because of this,"
    " you may wish to manually override the weightclass setting for all"
    " extra light, ultra light or thin fonts'"
    " - http://www.adobe.com/devnet/opentype/afdko/topic_font_wt_win.html"
    if weight_value < 250:
      bad_entries.append({"field": field,
                          "rec": "Value should idealy be 250 or more." +
                                 full_info})
    if weight_value > 900:
      bad_entries.append({"field": field,
                          "rec": "Value should idealy be 900 or less."})
  if len(bad_entries) > 0:
    table = "| Field | Recommendation |\n"
    table += "|:----- |:-------------- |\n"
    for bad in bad_entries:
      table += "| {} | {} |\n".format(bad["field"], bad["rec"])
    fb.info(("Font does not follow "
             "some family naming recommendations:\n\n"
             "{}").format(table))
  else:
    fb.ok("Font follows the family naming recommendations.")


def check_font_enables_smart_dropout_control(fb, font):
  ''' Font enables smart dropout control in 'prep' table instructions?

      B8 01 FF    PUSHW 0x01FF
      85          SCANCTRL (unconditinally turn on
                            dropout control mode)
      B0 04       PUSHB 0x04
      8D          SCANTYPE (enable smart dropout control)

      Smart dropout control means activating rules 1, 2 and 5:
      Rule 1: If a pixel's center falls within the glyph outline,
              that pixel is turned on.
      Rule 2: If a contour falls exactly on a pixel's center,
              that pixel is turned on.
      Rule 5: If a scan line between two adjacent pixel centers
              (either vertical or horizontal) is intersected
              by both an on-Transition contour and an off-Transition
              contour and neither of the pixels was already turned on
              by rules 1 and 2, turn on the pixel which is closer to
              the midpoint between the on-Transition contour and
              off-Transition contour. This is "Smart" dropout control.
  '''
  fb.new_check("072", "Font enables smart dropout control"
                      " in 'prep' table instructions?")
  instructions = "\xb8\x01\xff\x85\xb0\x04\x8d"
  if "CFF " in font:
    fb.skip("Not applicable to a CFF font.")
  else:
    try:
      bytecode = font['prep'].program.getBytecode()
    except KeyError:
      bytecode = ''

    if instructions in bytecode:
      fb.ok("Program at 'prep' table contains instructions"
            " enabling smart dropout control.")
    else:
      fb.warning("Font does not contain TrueType instructions enabling"
                 " smart dropout control in the 'prep' table program."
                 " Please try exporting the font with autohinting enabled.")


def check_MaxAdvanceWidth_is_consistent_with_Hmtx_and_Hhea_tables(fb, font):
  fb.new_check("073", "MaxAdvanceWidth is consistent with values"
                      " in the Hmtx and Hhea tables?")
  hhea_advance_width_max = font['hhea'].advanceWidthMax
  hmtx_advance_width_max = None
  for g in font['hmtx'].metrics.values():
    if hmtx_advance_width_max is None:
      hmtx_advance_width_max = max(0, g[0])
    else:
      hmtx_advance_width_max = max(g[0], hmtx_advance_width_max)

  if hmtx_advance_width_max is None:
    fb.error("Failed to find advance width data in HMTX table!")
  elif hmtx_advance_width_max != hhea_advance_width_max:
    fb.error("AdvanceWidthMax mismatch: expected %s (from hmtx);"
             " got %s (from hhea)") % (hmtx_advance_width_max,
                                       hhea_advance_width_max)
  else:
    fb.ok("MaxAdvanceWidth is consistent"
          " with values in the Hmtx and Hhea tables.")


def check_non_ASCII_chars_in_ASCII_only_NAME_table_entries(fb, font):
  fb.new_check("074", "Are there non-ASCII characters"
                      " in ASCII-only NAME table entries ?")
  bad_entries = []
  for name in font['name'].names:
    # Items with NameID > 18 are expressly for localising
    # the ASCII-only IDs into Hindi / Arabic / etc.
    if name.nameID >= 0 and name.nameID <= 18:
      string = name.string.decode(name.getEncoding())
      try:
        string.encode('ascii')
      except:
        bad_entries.append(name)
  if len(bad_entries) > 0:
    fb.error(('There are {} strings containing'
              ' non-ASCII characters in the ASCII-only'
              ' NAME table entries.').format(len(bad_entries)))
  else:
    fb.ok('None of the ASCII-only NAME table entries'
          ' contain non-ASCII characteres.')

##########################################################
##  Checks ported from:                                 ##
##  https://github.com/mekkablue/Glyphs-Scripts/        ##
##  blob/447270c7a82fa272acc312e120abb20f82716d08/      ##
##  Test/Preflight%20Font.py                            ##
##########################################################


def check_for_points_out_of_bounds(fb, font):
  fb.new_check("075", "Check for points out of bounds")
  failed = False
  for glyphName in font['glyf'].keys():
    glyph = font['glyf'][glyphName]
    coords = glyph.getCoordinates(font['glyf'])[0]
    for x, y in coords:
      if x < glyph.xMin or x > glyph.xMax or \
         y < glyph.yMin or y > glyph.yMax or \
         abs(x) > 32766 or abs(y) > 32766:
        failed = True
        fb.warning(("Glyph '{}' coordinates ({},{})"
                    " out of bounds."
                    " This happens a lot when points are not extremes,"
                    " which is usually bad. However, fixing this alert"
                    " by adding points on extremes may do more harm"
                    " than good, especially with italics,"
                    " calligraphic-script, handwriting, rounded and"
                    " other fonts. So it is common to"
                    " ignore this message.").format(glyphName, x, y))
  if not failed:
    fb.ok("All glyph paths have coordinates within bounds!")


def check_glyphs_have_unique_unicode_codepoints(fb, font):
  fb.new_check("076", "Check glyphs have unique unicode codepoints")
  failed = False
  for subtable in font['cmap'].tables:
    if subtable.isUnicode():
      codepoints = {}
      for codepoint, name in subtable.cmap.items():
        codepoints.setdefault(codepoint, set()).add(name)
      for value in codepoints.keys():
        if len(codepoints[value]) >= 2:
          failed = True
          fb.error(("These glyphs carry the same"
                    " unicode value {}:"
                    " {}").format(value,
                                  ", ".join(codepoints[value])))
  if not failed:
    fb.ok("All glyphs have unique unicode codepoint assignments.")


def check_all_glyphs_have_codepoints_assigned(fb, font):
  fb.new_check("077", "Check all glyphs have codepoints assigned")
  failed = False
  for subtable in font['cmap'].tables:
    if subtable.isUnicode():
      for item in subtable.cmap.items():
        codepoint = item[0]
        if codepoint is None:
          failed = True
          fb.error(("Glyph {} lacks a unicode"
                    " codepoint assignment").format(codepoint))
  if not failed:
    fb.ok("All glyphs have a codepoint value assigned.")


def check_that_glyph_names_do_not_exceed_max_length(fb, font):
  fb.new_check("078", "Check that glyph names do not exceed max length")
  failed = False
  for subtable in font['cmap'].tables:
    for item in subtable.cmap.items():
      name = item[1]
      if len(name) > 109:
        failed = True
        fb.error(("Glyph name is too long:"
                  " '{}'").format(name))
  if not failed:
    fb.ok("No glyph names exceed max allowed length.")


def check_METADATA_Ensure_designer_simple_short_name(fb, family):
  fb.new_check("080", "METADATA.pb: Ensure designer simple short name.")
  if len(family.designer.split(' ')) >= 4 or\
     ' and ' in family.designer or\
     '.' in family.designer or\
     ',' in family.designer:
    fb.error('`designer` key must be simple short name')
  else:
    fb.ok('Designer is a simple short name')


def check_family_is_listed_in_GFDirectory(fb, family):
  fb.new_check("081", "METADATA.pb: Fontfamily is listed"
                      " in Google Font Directory ?")
  url = ('http://fonts.googleapis.com'
         '/css?family=%s') % family.name.replace(' ', '+')
  try:
    r = requests.get(url)
    if r.status_code != 200:
      fb.error('No family found in GWF in %s' % url)
    else:
      fb.ok('Font is properly listed in Google Font Directory.')
      return url
  except:
    fb.warning("Failed to query GWF at {}".format(url))


def check_METADATA_Designer_exists_in_GWF_profiles_csv(fb, family):
  fb.new_check("082", "METADATA.pb: Designer exists in GWF profiles.csv ?")
  PROFILES_GIT_URL = ('https://github.com/google/'
                      'fonts/blob/master/designers/profiles.csv')
  PROFILES_RAW_URL = ('https://raw.githubusercontent.com/google/'
                      'fonts/master/designers/profiles.csv')
  if family.designer == "":
    fb.error('METADATA.pb field "designer" MUST NOT be empty!')
  elif family.designer == "Multiple Designers":
    fb.skip("Found 'Multiple Designers' at METADATA.pb, which is OK,"
            "so we won't look for it at profiles.cvs")
  else:
    try:
      handle = urllib.urlopen(PROFILES_RAW_URL)
      designers = []
      for row in csv.reader(handle):
        if not row:
          continue
        designers.append(row[0].decode('utf-8'))
      if family.designer not in designers:
        fb.warning(("METADATA.pb: Designer '{}' is not listed"
                    " in profiles.csv"
                    " (at '{}')").format(family.designer,
                                         PROFILES_GIT_URL))
      else:
        fb.ok(("Found designer '{}'"
               " at profiles.csv").format(family.designer))
    except:
      fb.warning("Failed to fetch '{}'".format(PROFILES_RAW_URL))


def check_METADATA_has_unique_full_name_values(fb, family):
  fb.new_check("083", "METADATA.pb: check if fonts field"
                      " only has unique 'full_name' values")
  fonts = {}
  for x in family.fonts:
    fonts[x.full_name] = x
  if len(set(fonts.keys())) != len(family.fonts):
    fb.error("Found duplicated 'full_name' values"
             " in METADATA.pb fonts field")
  else:
    fb.ok("METADATA.pb 'fonts' field only has unique 'full_name' values")


def check_METADATA_check_style_weight_pairs_are_unique(fb, family):
  fb.new_check("084", "METADATA.pb: check if fonts field"
                      " only contains unique style:weight pairs")
  pairs = {}
  for f in family.fonts:
    styleweight = '%s:%s' % (f.style, f.weight)
    pairs[styleweight] = 1
  if len(set(pairs.keys())) != len(family.fonts):
    logging.error("Found duplicated style:weight pair"
                  " in METADATA.pb fonts field")
  else:
    fb.ok("METADATA.pb 'fonts' field only has unique style:weight pairs")


def check_METADATA_license_is_APACHE2_UFL_or_OFL(fb, family):
  fb.new_check("085", "METADATA.pb license is 'APACHE2', 'UFL' or 'OFL' ?")
  licenses = ['APACHE2', 'OFL', 'UFL']
  if family.license in licenses:
    fb.ok(("Font license is declared"
           " in METADATA.pb as '{}'").format(family.license))
  else:
    fb.error(("METADATA.pb license field ('{}')"
              " must be one of the following: {}").format(
                family.license,
                licenses))


def check_METADATA_contains_at_least_menu_and_latin_subsets(fb, family):
  fb.new_check("086", "METADATA.pb should contain at least"
                      " 'menu' and 'latin' subsets.")
  missing = []
  for s in ["menu", "latin"]:
    if s not in list(family.subsets):
      missing.append(s)

  if missing != []:
    fb.error(("Subsets 'menu' and 'latin' are mandatory, but METADATA.pb"
              " is missing '{}'").format(' and '.join(missing)))
  else:
    fb.ok("METADATA.pb contains 'menu' and 'latin' subsets.")


def check_METADATA_subsets_alphabetically_ordered(fb, path, family):
  fb.new_check("087", "METADATA.pb subsets should be alphabetically ordered.")
  expected = list(sorted(family.subsets))

  if list(family.subsets) != expected:
    if fb.config["autofix"]:
      fb.hotfix(("METADATA.pb subsets were not sorted "
                 "in alphabetical order: ['{}']"
                 " We're hotfixing that"
                 " to ['{}']").format("', '".join(family.subsets),
                                      "', '".join(expected)))
      del family.subsets[:]
      family.subsets.extend(expected)

      save_FamilyProto_Message(path, family)
    else:
      fb.error(("METADATA.pb subsets are not sorted "
                "in alphabetical order: Got ['{}']"
                " and expected ['{}']").format("', '".join(family.subsets),
                                               "', '".join(expected)))
  else:
    fb.ok("METADATA.pb subsets are sorted in alphabetical order")


def check_Copyright_notice_is_the_same_in_all_fonts(fb, family):
  fb.new_check("088", "Copyright notice is the same in all fonts ?")
  copyright = ''
  fail = False
  for font_metadata in family.fonts:
    if copyright and font_metadata.copyright != copyright:
      fail = True
    copyright = font_metadata.copyright
  if fail:
    fb.error('METADATA.pb: Copyright field value'
             ' is inconsistent across family')
  else:
    fb.ok('Copyright is consistent across family')


def check_METADATA_family_values_are_all_the_same(fb, family):
  fb.new_check("089", "Check that METADATA family values are all the same")
  name = ''
  fail = False
  for font_metadata in family.fonts:
    if name and font_metadata.name != name:
      fail = True
    name = font_metadata.name
  if fail:
    fb.error("METADATA.pb: Family name is not the same"
             " in all metadata 'fonts' items.")
  else:
    fb.ok("METADATA.pb: Family name is the same"
          " in all metadata 'fonts' items.")


def check_font_has_regular_style(fb, family):
  fb.new_check("090", "According GWF standards"
                      " font should have Regular style.")
  found = False
  for f in family.fonts:
    if f.weight == 400 and f.style == 'normal':
      found = True
  if found:
    fb.ok("Font has a Regular style.")
  else:
    fb.error("This font lacks a Regular"
             " (style: normal and weight: 400)"
             " as required by GWF standards.")
  return found


def check_regular_is_400(fb, family, found):
  fb.new_check("091", "Regular should be 400")
  if not found:
    fb.skip("This test will only run if font has a Regular style")
  else:
    badfonts = []
    for f in family.fonts:
      if f.full_name.endswith('Regular') and f.weight != 400:
        badfonts.append("{} (weight: {})".format(f.filename, f.weight))
    if len(badfonts) > 0:
      fb.error(('METADATA.pb: Regular font weight must be 400.'
                ' Please fix: {}').format(', '.join(badfonts)))
    else:
      fb.ok('Regular has weight=400')


def check_font_on_disk_and_METADATA_have_same_family_name(fb, font, f):
  fb.new_check("092", "Font on disk and in METADATA.pb"
                      " have the same family name ?")
  familynames = get_name_string(font, NAMEID_FONT_FAMILY_NAME)
  if len(familynames) == 0:
    fb.error(("This font lacks a FONT_FAMILY_NAME entry"
              " (nameID={}) in the name"
              " table.").format(NAMEID_FONT_FAMILY_NAME))
  else:
    if f.name not in familynames:
      fb.error(('Unmatched family name in font:'
                ' TTF has "{}" while METADATA.pb'
                ' has "{}"').format(familynames, f.name))
    else:
      fb.ok(("Family name '{}' is identical"
             " in METADATA.pb and on the"
             " TTF file.").format(f.name))


def check_METADATA_postScriptName_matches_name_table_value(fb, font, f):
  fb.new_check("093", "Checks METADATA.pb 'postScriptName'"
                      " matches TTF 'postScriptName'")
  postscript_names = get_name_string(font, NAMEID_POSTSCRIPT_NAME)
  if len(postscript_names) == 0:
    fb.error(("This font lacks a POSTSCRIPT_NAME"
              " entry (nameID={}) in the "
              "name table.").format(NAMEID_POSTSCRIPT_NAME))
  else:
    postscript_name = postscript_names[0]

    if postscript_name != f.post_script_name:
      fb.error(('Unmatched postscript name in font:'
                ' TTF has "{}" while METADATA.pb has'
                ' "{}"').format(postscript_name,
                                f.post_script_name))
    else:
      fb.ok(("Postscript name '{}' is identical"
             " in METADATA.pb and on the"
             " TTF file.").format(f.post_script_name))


def check_METADATA_fullname_matches_name_table_value(fb, font, f):
  fb.new_check("094", "METADATA.pb 'fullname' value"
                      " matches internal 'fullname' ?")
  full_fontnames = get_name_string(font, NAMEID_FULL_FONT_NAME)
  if len(full_fontnames) == 0:
    fb.error(("This font lacks a FULL_FONT_NAME"
              " entry (nameID={}) in the "
              "name table.").format(NAMEID_FULL_FONT_NAME))
  else:
    full_fontname = full_fontnames[0]

    if full_fontname != f.full_name:
      fb.error(('Unmatched fullname in font:'
                ' TTF has "{}" while METADATA.pb'
                ' has "{}"').format(full_fontname, f.full_name))
    else:
      fb.ok(("Full fontname '{}' is identical"
             " in METADATA.pb and on the "
             "TTF file.").format(full_fontname))


def check_METADATA_fonts_name_matches_font_familyname(fb, font, f):
  fb.new_check("095", "METADATA.pb fonts 'name' property"
                      " should be same as font familyname")
  font_familynames = get_name_string(font, NAMEID_FONT_FAMILY_NAME)
  if len(font_familynames) == 0:
    fb.error(("This font lacks a FONT_FAMILY_NAME entry"
              " (nameID={}) in the "
              "name table.").format(NAMEID_FONT_FAMILY_NAME))
  else:
    font_familyname = font_familynames[0]

    if font_familyname not in f.name:
      fb.error(('Unmatched familyname in font:'
                ' TTF has "{}" while METADATA.pb has'
                ' name="{}"').format(font_familyname, f.name))
    else:
      fb.ok(("OK: Family name '{}' is identical"
             " in METADATA.pb and on the"
             " TTF file.").format(f.name))


def check_METADATA_fullName_matches_postScriptName(fb, f):
  fb.new_check("096", "METADATA.pb 'fullName' matches 'postScriptName' ?")
  regex = re.compile(r'\W')
  post_script_name = regex.sub('', f.post_script_name)
  fullname = regex.sub('', f.full_name)
  if fullname != post_script_name:
    fb.error(('METADATA.pb full_name="{0}"'
              ' does not match post_script_name ='
              ' "{1}"').format(f.full_name,
                               f.post_script_name))
  else:
    fb.ok("METADATA.pb fields 'fullName' and"
          " 'postScriptName' have the same value.")


def check_METADATA_filename_matches_postScriptName(fb, f):
  fb.new_check("097", "METADATA.pb 'filename' matches 'postScriptName' ?")
  regex = re.compile(r'\W')
  post_script_name = regex.sub('', f.post_script_name)
  filename = regex.sub('', os.path.splitext(f.filename)[0])
  if filename != post_script_name:
    msg = ('METADATA.pb filename="{0}" does not match '
           'post_script_name="{1}."')
    fb.error(msg.format(f.filename, f.post_script_name))
  else:
    fb.ok("METADATA.pb fields 'filename' and"
          " 'postScriptName' have matching values.")


def check_METADATA_name_contains_good_font_name(fb, font, f):
  fb.new_check("098", "METADATA.pb 'name' contains font name"
                      " in right format ?")
  font_familynames = get_name_string(font, NAMEID_FONT_FAMILY_NAME)
  if len(font_familynames) == 0:
    fb.error("A corrupt font that lacks a font_family"
             " nameID entry caused a whole sequence"
             " of tests to be skipped.")
    return None
  else:
    font_familyname = font_familynames[0]

    if font_familyname in f.name:
      fb.ok("METADATA.pb 'name' contains font name"
            " in right format.")
    else:
      fb.error(("METADATA.pb name='{}' does not match"
                " correct font name format.").format(f.name))
    return font_familyname


def check_METADATA_fullname_contains_good_fname(fb, f, font_familyname):
  fb.new_check("099", "METADATA.pb 'full_name' contains"
                      " font name in right format ?")
  if font_familyname in f.name:
    fb.ok("METADATA.pb 'full_name' contains"
          " font name in right format.")
  else:
    fb.error(("METADATA.pb full_name='{}' does not match"
              " correct font name format.").format(f.full_name))


def check_METADATA_filename_contains_good_fname(fb, f, font_familyname):
  fb.new_check("100", "METADATA.pb 'filename' contains"
                      " font name in right format ?")
  if "".join(str(font_familyname).split()) in f.filename:
    fb.ok("METADATA.pb 'filename' contains"
          " font name in right format.")
  else:
    fb.error(("METADATA.pb filename='{}' does not match"
              " correct font name format.").format(f.filename))


def check_METADATA_postScriptName_contains_good_fname(fb, f, familyname):
  fb.new_check("101", "METADATA.pb 'postScriptName' contains"
                      " font name in right format ?")
  if "".join(str(familyname).split()) in f.post_script_name:
    fb.ok("METADATA.pb 'postScriptName' contains"
          " font name in right format ?")
  else:
    fb.error(("METADATA.pb postScriptName='{}'"
              " does not match correct"
              " font name format.").format(f.post_script_name))


def check_Copyright_notice_matches_canonical_pattern(fb, f):
  fb.new_check("102", "Copyright notice matches canonical pattern?")
  almost_matches = re.search(r'(Copyright\s+20\d{2}.+)',
                             f.copyright)
  does_match = re.search(r'(Copyright\s+20\d{2}\s+.*\(.+@.+\..+\))',
                         f.copyright)
  if (does_match is not None):
    fb.ok("METADATA.pb copyright field matches canonical pattern.")
  else:
    if (almost_matches):
      fb.warning(("METADATA.pb: Copyright notice is okay,"
                  " but it lacks an email address."
                  " Expected pattern is:"
                  " 'Copyright 2016 Author Name (name@site.com)'\n"
                  "But detected copyright string is:"
                  " '{}'").format(unidecode(f.copyright)))
    else:
      fb.error(("METADATA.pb: Copyright notices should match"
                " the folowing pattern:"
                " 'Copyright 2016 Author Name (name@site.com)'\n"
                "But instead we have got:"
                " '{}'").format(unidecode(f.copyright)))


def check_Copyright_notice_does_not_contain_Reserved_Name(fb, f):
  fb.new_check("103", "Copyright notice does not "
                      "contain Reserved Font Name")
  if 'Reserved Font Name' in f.copyright:
    fb.warning(("METADATA.pb: copyright field ('{}')"
                " contains 'Reserved Font Name'."
                " This is an error except in a few specific"
                " rare cases.").format(unidecode(f.copyright)))
  else:
    fb.ok('METADATA.pb copyright field'
          ' does not contain "Reserved Font Name"')


def check_Copyright_notice_does_not_exceed_500_chars(fb, f):
  fb.new_check("104", "Copyright notice shouldn't exceed 500 chars")
  if len(f.copyright) > 500:
    fb.error("METADATA.pb: Copyright notice exceeds"
             " maximum allowed lengh of 500 characteres.")
  else:
    fb.ok("Copyright notice string is"
          " shorter than 500 chars.")


def check_Filename_is_set_canonically(fb, f):
  fb.new_check("105", "Filename is set canonically in METADATA.pb ?")

  def create_canonical_filename(font_metadata):
    style_names = {
     'normal': '',
     'italic': 'Italic'
    }
    familyname = font_metadata.name.replace(' ', '')
    style_weight = '%s%s' % (WEIGHT_VALUE_TO_NAME.get(font_metadata.weight),
                             style_names.get(font_metadata.style))
    if not style_weight:
        style_weight = 'Regular'
    return '%s-%s.ttf' % (familyname, style_weight)

  canonical_filename = create_canonical_filename(f)
  if canonical_filename != f.filename:
    fb.error("METADATA.pb: filename field ('{}')"
             " does not match"
             " canonical name '{}'".format(f.filename,
                                           canonical_filename))
  else:
    fb.ok('Filename in METADATA.pb is set canonically.')


def check_METADATA_font_italic_matches_font_internals(fb, font, f):
  fb.new_check("106", "METADATA.pb font.style `italic`"
                      " matches font internals?")
  if f.style != 'italic':
    fb.skip("This test only applies to italic fonts.")
  else:
    font_familyname = get_name_string(font, NAMEID_FONT_FAMILY_NAME)
    font_fullname = get_name_string(font, NAMEID_FULL_FONT_NAME)
    if len(font_familyname) == 0 or len(font_fullname) == 0:
      fb.skip("Font lacks familyname and/or"
              " fullname entries in name table.")
      # these fail scenarios were already tested above
      # (passing those previous tests is a prerequisite for this one)
    else:
      font_familyname = font_familyname[0]
      font_fullname = font_fullname[0]

      if not bool(font['head'].macStyle & MACSTYLE_ITALIC):
          fb.error('METADATA.pb style has been set to italic'
                   ' but font macStyle is improperly set')
      elif not font_familyname.split('-')[-1].endswith('Italic'):
          fb.error(('Font macStyle Italic bit is set'
                    ' but nameID %d ("%s")'
                    ' is not ended '
                    'with "Italic"') % (NAMEID_FONT_FAMILY_NAME,
                                        font_familyname))
      elif not font_fullname.split('-')[-1].endswith('Italic'):
          fb.error(('Font macStyle Italic bit is set'
                    ' but nameID %d ("%s")'
                    ' is not ended'
                    ' with "Italic"') % (NAMEID_FULL_FONT_NAME,
                                         font_fullname))
      else:
        fb.ok("OK: METADATA.pb font.style 'italic'"
              " matches font internals.")


def check_METADATA_fontstyle_normal_matches_internals(fb, font, f):
  fb.new_check("107", "METADATA.pb font.style `normal`"
                      " matches font internals?")
  if f.style != 'normal':
    fb.skip("This test only applies to normal fonts.")
  else:
    font_familyname = get_name_string(font, NAMEID_FONT_FAMILY_NAME)
    font_fullname = get_name_string(font, NAMEID_FULL_FONT_NAME)
    if len(font_familyname) == 0 or len(font_fullname) == 0:
      fb.skip("Font lacks familyname and/or"
              " fullname entries in name table.")
      # these fail scenarios were already tested above
      # (passing those previous tests is a prerequisite for this one)
      return False
    else:
      font_familyname = font_familyname[0]
      font_fullname = font_fullname[0]

      if bool(font['head'].macStyle & MACSTYLE_ITALIC):
          fb.error('METADATA.pb style has been set to normal'
                   ' but font macStyle is improperly set')
      elif font_familyname.split('-')[-1].endswith('Italic'):
          fb.error(('Font macStyle indicates a non-Italic font,'
                    ' but nameID %d (FONT_FAMILY_NAME: "%s") ends'
                    ' with "Italic"').format(NAMEID_FONT_FAMILY_NAME,
                                             font_familyname))
      elif font_fullname.split('-')[-1].endswith('Italic'):
          fb.error('Font macStyle indicates a non-Italic font'
                   ' but nameID %d (FULL_FONT_NAME: "%s") ends'
                   ' with "Italic"'.format(NAMEID_FULL_FONT_NAME,
                                           font_fullname))
      else:
        fb.ok("METADATA.pb font.style 'normal'"
              " matches font internals.")
      return True


def check_Metadata_keyvalue_match_to_table_name_fields(fb, font, f):
  fb.new_check("108", "Metadata key-value match to table name fields?")
  font_familyname = get_name_string(font, NAMEID_FONT_FAMILY_NAME)[0]
  font_fullname = get_name_string(font, NAMEID_FULL_FONT_NAME)[0]
  if font_familyname != f.name:
    fb.error(("METADATA.pb Family name '{}')"
              " does not match name table"
              " entry '{}' !").format(f.name,
                                      font_familyname))
  elif font_fullname != f.full_name:
    fb.error(("METADATA.pb: Fullname ('{}')"
              " does not match name table"
              " entry '{}' !").format(f.full_name,
                                      font_fullname))
  else:
    fb.ok("METADATA.pb familyname and fullName fields"
          " match corresponding name table entries.")


def check_fontname_is_not_camel_cased(fb, f):
  fb.new_check("109", "Check if fontname is not camel cased.")
  if bool(re.match(r'([A-Z][a-z]+){2,}', f.name)):
    fb.error(("METADATA.pb: '%s' is a CamelCased name."
              " To solve this, simply use spaces"
              " instead in the font name.").format(f.name))
  else:
    fb.ok("Font name is not camel-cased.")


def check_font_name_is_the_same_as_family_name(fb, family, f):
  fb.new_check("110", "Check font name is the same as family name.")
  if f.name != family.name:
    fb.error(('METADATA.pb: %s: Family name "%s"'
              ' does not match'
              ' font name: "%s"').format(f.filename,
                                         family.name,
                                         f.name))
  else:
    fb.ok('Font name is the same as family name.')


def check_font_weight_has_a_canonical_value(fb, f):
  fb.new_check("111", "Check that font weight has a canonical value")
  first_digit = f.weight / 100
  if (f.weight % 100) != 0 or (first_digit < 1 or first_digit > 9):
    fb.error(("METADATA.pb: The weight is declared"
              " as {} which is not a "
              "multiple of 100"
              " between 100 and 900.").format(f.weight))
  else:
    fb.ok("Font weight has a canonical value.")


def check_METADATA_weigth_matches_OS2_usWeightClass_value(fb, f):
  fb.new_check("112", "Checking OS/2 usWeightClass"
                      " matches weight specified at METADATA.pb")
  fb.assert_table_entry('OS/2', 'usWeightClass', f.weight)
  fb.log_results("OS/2 usWeightClass matches "
                 "weight specified at METADATA.pb")


weights = {
  'Thin': 100,
  'ThinItalic': 100,
  'ExtraLight': 200,
  'ExtraLightItalic': 200,
  'Light': 300,
  'LightItalic': 300,
  'Regular': 400,
  'Italic': 400,
  'Medium': 500,
  'MediumItalic': 500,
  'SemiBold': 600,
  'SemiBoldItalic': 600,
  'Bold': 700,
  'BoldItalic': 700,
  'ExtraBold': 800,
  'ExtraBoldItalic': 800,
  'Black': 900,
  'BlackItalic': 900,
}


def check_Metadata_weight_matches_postScriptName(fb, f):
  fb.new_check("113", "Metadata weight matches postScriptName")
  pair = []
  for k, weight in weights.items():
    if weight == f.weight:
      pair.append((k, weight))

  if not pair:
    fb.error('METADATA.pb: Font weight'
             ' does not match postScriptName')
  elif not (f.post_script_name.endswith('-' + pair[0][0]) or
            f.post_script_name.endswith('-%s' % pair[1][0])):
    fb.error('METADATA.pb: postScriptName ("{}")'
             ' with weight {} must be '.format(f.post_script_name,
                                               pair[0][1]) +
             'ended with "{}" or "{}"'.format(pair[0][0],
                                              pair[1][0]))
  else:
    fb.ok("Weight value matches postScriptName.")


def check_METADATA_lists_fonts_named_canonicaly(fb, font, f):
  fb.new_check("114", "METADATA.pb lists fonts named canonicaly?")
  font_familyname = get_name_string(font, NAMEID_FONT_FAMILY_NAME)
  if len(font_familyname) == 0:
    fb.skip("Skipping this test due to the lack"
            " of a FONT_FAMILY_NAME in the name table.")
  else:
    font_familyname = font_familyname[0]

    is_canonical = False
    _weights = []
    for value, intvalue in weights.items():
      if intvalue == font['OS/2'].usWeightClass:
        _weights.append(value)

    for w in _weights:
      canonical_name = "%s %s" % (font_familyname, w)
      if f.full_name == canonical_name:
        is_canonical = True

    if is_canonical:
      fb.ok("METADATA.pb lists fonts named canonicaly.")
    else:
      v = map(lambda x: font_familyname + ' ' + x, _weights)
      fb.error('Canonical name in font: Expected "%s"'
               ' but got "%s" instead.' % ('" or "'.join(v),
                                           f.full_name))


def check_Font_styles_are_named_canonically(fb, font, f):
  fb.new_check("115", "Font styles are named canonically?")

  def find_italic_in_name_table():
    for entry in font['name'].names:
      if 'italic' in entry.string.decode(
       entry.getEncoding()).lower():
        return True
    return False

  def is_italic():
    return (font['head'].macStyle & MACSTYLE_ITALIC or
            font['post'].italicAngle or
            find_italic_in_name_table())

  if f.style not in ['italic', 'normal']:
    fb.skip("This check only applies to font styles declared"
            " as 'italic' or 'regular' on METADATA.pb")
  else:
    if is_italic() and f.style != 'italic':
      fb.error("The font style is %s"
               " but it should be italic" % (f.style))
    elif not is_italic() and f.style != 'normal':
      fb.error(("The font style is %s"
                " but it should be normal") % (f.style))
    else:
      fb.ok("Font styles are named canonically")


def check_font_em_size_is_ideally_equal_to_1000(fb, font, skip_gfonts):
  fb.new_check("116", "Is font em size (ideally) equal to 1000?")
  if skip_gfonts:
    fb.skip("Skipping this Google-Fonts specific check.")
  else:
    upm_height = font['head'].unitsPerEm
    if upm_height != 1000:
      fb.warning(("font em size ({}) is not"
                  " equal to 1000.").format(upm_height))
    else:
      fb.ok("Font em size is equal to 1000.")


def check_regression_v_number_increased(fb, new_font, old_font, f):
  fb.new_check("117", "Version number has increased since previous release?")
  new_v_number = new_font['head'].fontRevision
  old_v_number = old_font['head'].fontRevision
  if new_v_number < old_v_number:
    fb.error(("Version number %s is less than or equal to"
              " old version %s") % (new_v_number, old_v_number))
  else:
    fb.ok(("Version number %s is greater than"
           " old version %s") % (new_v_number, old_v_number))


def check_regression_glyphs_structure(fb, new_font, old_font, f):
  fb.new_check("118", "Glyphs are similiar to old version")
  bad_glyphs = []
  new_glyphs = glyphs_surface_area(new_font)
  old_glyphs = glyphs_surface_area(old_font)

  shared_glyphs = set(new_glyphs) & set(old_glyphs)

  for glyph in shared_glyphs:
    if abs(int(new_glyphs[glyph]) - int(old_glyphs[glyph])) > 8000:
      bad_glyphs.append(glyph)

  if bad_glyphs:
    fb.error("Following glyphs differ greatly from previous version: [%s]" % (
      ', '.join(bad_glyphs)
    ))
  else:
    fb.ok("Yes, the glyphs are similar "
          "in comparison to the previous version.")


def check_regression_ttfauto_xheight_increase(fb, new_font, old_font, f):
  fb.new_check("119", "TTFAutohint x-height increase value is"
                      " same as previouse release?")
  new_inc_xheight = None
  old_inc_xheight = None

  if 'fpgm' in new_font:
    new_fpgm_tbl = new_font['fpgm'].program.getAssembly()
    new_inc_xheight = ttfauto_fpgm_xheight_rounding(fb,
                                                    new_fpgm_tbl,
                                                    "this fontfile")
  if 'fpgm' in old_font:
    old_fpgm_tbl = old_font['fpgm'].program.getAssembly()
    old_inc_xheight = ttfauto_fpgm_xheight_rounding(fb,
                                                    old_fpgm_tbl,
                                                    "previous release")
  if new_inc_xheight != old_inc_xheight:
    fb.error("TTFAutohint --increase-x-height is %s. "
             "It should match the previous version's value %s" %
             (new_inc_xheight, old_inc_xheight)
             )
  else:
    fb.ok("TTFAutohint --increase-x-height is the same as the previous "
          "release, %s" % (new_inc_xheight))


###############################
# Upstream Font Source checks #
###############################

def check_all_fonts_have_matching_glyphnames(fb, folder, directory):
  fb.new_check(120, "Each font in family has matching glyph names?")
  glyphs = None
  failed = False
  for f in directory.get_fonts():
    try:
      font = PiFont(os.path.join(folder, f))
      if glyphs is None:
        glyphs = font.get_glyphs()
      elif glyphs != font.get_glyphs():
        failed = True
        fb.error(("Font '{}' has different glyphs in"
                  " comparison to onther fonts"
                  " in this family.").format(f))
        break
    except:
      failed = True
      fb.error("Failed to load font file: '{}'".format(f))

  if failed is False:
    fb.ok("All fonts in family have matching glyph names.")


def check_glyphs_have_same_num_of_contours(fb, folder, directory):
  fb.new_check("121", "Glyphs have same number of contours across family ?")
  glyphs = {}
  failed = False
  for f in directory.get_fonts():
    font = PiFont(os.path.join(folder, f))
    for glyphcode, glyphname in font.get_glyphs():
      contours = font.get_contours_count(glyphname)
      if glyphcode in glyphs and glyphs[glyphcode] != contours:
        failed = True
        fb.error(("Number of contours of glyph '{}'"
                  " does not match."
                  " Expected {} contours, but actual is"
                  " {} contours").format(glyphname,
                                         glyphs[glyphcode],
                                         contours))
      glyphs[glyphcode] = contours
  if failed is False:
    fb.ok("Glyphs have same number of contours across family.")


def check_glyphs_have_same_num_of_points(fb, folder, directory):
  fb.new_check("122", "Glyphs have same number of points across family ?")
  glyphs = {}
  failed = False
  for f in directory.get_fonts():
    font = PiFont(os.path.join(folder, f))
    for g, glyphname in font.get_glyphs():
      points = font.get_points_count(glyphname)
      if g in glyphs and glyphs[g] != points:
        failed = True
        fb.error(("Number of points of glyph '{}' does not match."
                  " Expected {} points, but actual is"
                  " {} points").format(glyphname,
                                       glyphs[g],
                                       points))
      glyphs[g] = points
  if failed is False:
    fb.ok("Glyphs have same number of points across family.")


def check_font_folder_contains_a_COPYRIGHT_file(fb, folder):
  fb.new_check("123", "Does this font folder contain COPYRIGHT file ?")
  assertExists(fb, folder, "COPYRIGHT.txt",
               "Font folder lacks a copyright file at '{}'",
               "Font folder contains COPYRIGHT.txt")


def check_font_folder_contains_a_DESCRIPTION_file(fb, folder):
  fb.new_check("124", "Does this font folder contain a DESCRIPTION file ?")
  assertExists(fb, folder, "DESCRIPTION.en_us.html",
               "Font folder lacks a description file at '{}'",
               "Font folder should contain DESCRIPTION.en_us.html.")


def check_font_folder_contains_licensing_files(fb, folder):
  fb.new_check("125", "Does this font folder contain licensing files?")
  assertExists(fb, folder, ["LICENSE.txt", "OFL.txt"],
               "Font folder lacks licensing files at '{}'",
               "Font folder should contain licensing files.")


def check_font_folder_contains_a_FONTLOG_txt_file(fb, folder):
  fb.new_check("126", "Font folder should contain FONTLOG.txt")
  assertExists(fb, folder, "FONTLOG.txt",
               "Font folder lacks a fontlog file at '{}'",
               "Font folder should contain a 'FONTLOG.txt' file.")


def check_repository_contains_METADATA_pb_file(fb, f):
  fb.new_check("127", "Repository contains METADATA.pb file?")
  fullpath = os.path.join(f, 'METADATA.pb')
  if not os.path.exists(fullpath):
    fb.error("File 'METADATA.pb' does not exist"
             " in root of upstream repository")
  else:
    fb.ok("Repository contains METADATA.pb file.")


def check_copyright_notice_is_consistent_across_family(fb, folder):
  fb.new_check("128", "Copyright notice is consistent"
                      " across all fonts in this family ?")

  COPYRIGHT_REGEX = re.compile(r'Copyright.*?20\d{2}.*', re.U | re.I)

  def grep_copyright_notice(contents):
    match = COPYRIGHT_REGEX.search(contents)
    if match:
      return match.group(0).strip(',\r\n')
    return

  def lookup_copyright_notice(ufo_folder):
    # current_path = ufo_folder
    try:
      contents = open(os.path.join(ufo_folder,
                                   'fontinfo.plist')).read()
      copyright = grep_copyright_notice(contents)
      if copyright:
        return copyright
    except (IOError, OSError):
      pass

    # TODO: FIX-ME!
    # I'm not sure what's going on here:
    # "?" was originaly "self.operator.path" in the old codebase:
#    while os.path.realpath(?) != current_path:
#      # look for all text files inside folder
#      # read contents from them and compare with copyright notice pattern
#      files = glob.glob(os.path.join(current_path, '*.txt'))
#      files += glob.glob(os.path.join(current_path, '*.ttx'))
#      for filename in files:
#        with open(os.path.join(current_path, filename)) as fp:
#          match = COPYRIGHT_REGEX.search(fp.read())
#          if not match:
#            continue
#          return match.group(0).strip(',\r\n')
#      current_path = os.path.join(current_path, '..')  # go up
#      current_path = os.path.realpath(current_path)
    return

  ufo_dirs = []
  for item in os.walk(folder):
    root = item[0]
    dirs = item[1]
    # files = item[2]
    for d in dirs:
        fullpath = os.path.join(root, d)
        if os.path.splitext(fullpath)[1].lower() == '.ufo':
            ufo_dirs.append(fullpath)
  if len(ufo_dirs) == 0:
    fb.skip("No UFO font file found.")
  else:
    failed = False
    copyright = None
    for ufo_folder in ufo_dirs:
      current_notice = lookup_copyright_notice(ufo_folder)
      if current_notice is None:
        continue
      if copyright is not None and current_notice != copyright:
        failed = True
        fb.error('"{}" != "{}"'.format(current_notice,
                                       copyright))
        break
      copyright = current_notice
    if failed is False:
      fb.ok("Copyright notice is consistent across all fonts in this family.")


def check_OS2_fsSelection(fb, font, style):
  fb.new_check("129", "Checking OS/2 fsSelection value")

  # Checking fsSelection REGULAR bit:
  check_bit_entry(fb, font, "OS/2", "fsSelection",
                  "Regular" in style or
                  (style in STYLE_NAMES and
                   style not in RIBBI_STYLE_NAMES and
                   "Italic" not in style),
                  bitmask=FSSEL_REGULAR,
                  bitname="REGULAR")

  # Checking fsSelection ITALIC bit:
  check_bit_entry(fb, font, "OS/2", "fsSelection",
                  "Italic" in style,
                  bitmask=FSSEL_ITALIC,
                  bitname="ITALIC")

  # Checking fsSelection BOLD bit:
  check_bit_entry(fb, font, "OS/2", "fsSelection",
                  style in ["Bold", "BoldItalic"],
                  bitmask=FSSEL_BOLD,
                  bitname="BOLD")


def check_post_italicAngle(fb, font, style):
  fb.new_check("130", "Checking post.italicAngle value")
  failed = False
  value = font['post'].italicAngle

  # Checking that italicAngle <= 0
  if value > 0:
    failed = True
    if fb.config['autofix']:
      font['post'].italicAngle = -value
      fb.hotfix(("post.italicAngle"
                 " from {} to {}").format(value, -value))
    else:
      fb.error(("post.italicAngle value must be changed"
                " from {} to {}").format(value, -value))
    value = -value

  # Checking that italicAngle is less than 20 degrees:
  if abs(value) > 20:
    failed = True
    if fb.config['autofix']:
      font['post'].italicAngle = -20
      fb.hotfix(("post.italicAngle"
                 " changed from {} to -20").format(value))
    else:
      fb.error(("post.italicAngle value must be"
                " changed from {} to -20").format(value))

  # Checking if italicAngle matches font style:
  if "Italic" in style:
    if font['post'].italicAngle == 0:
      failed = True
      fb.error("Font is italic, so post.italicAngle"
               " should be non-zero.")
  else:
    if font['post'].italicAngle != 0:
      failed = True
      fb.error("Font is not italic, so post.italicAngle"
               " should be equal to zero.")

  if not failed:
    fb.ok("post.italicAngle is {}".format(value))


def check_head_macStyle(fb, font, style):
  fb.new_check("131", "Checking head.macStyle value")

  # Checking macStyle ITALIC bit:
  check_bit_entry(fb, font, "head", "macStyle",
                  "Italic" in style,
                  bitmask=MACSTYLE_ITALIC,
                  bitname="ITALIC")

  # Checking macStyle BOLD bit:
  check_bit_entry(fb, font, "head", "macStyle",
                  style in ["Bold", "BoldItalic"],
                  bitmask=MACSTYLE_BOLD,
                  bitname="BOLD")


def check_with_pyfontaine(fb, font_file, glyphset):
  try:
    import subprocess
    fontaine_output = subprocess.check_output(["pyfontaine",
                                               "--missing",
                                               "--set", glyphset,
                                               font_file],
                                              stderr=subprocess.STDOUT)
    if "Support level: full" not in fontaine_output:
      fb.error(("pyfontaine output follows:\n\n"
                "{}\n").format(fontaine_output))
    else:
      fb.ok("pyfontaine passed this file")
  except subprocess.CalledProcessError, e:
    fb.error(("pyfontaine returned an error code. Output follows :"
              "\n\n{}\n").format(e.output))
  except OSError:
    # This is made very prominent with additional line breaks
    fb.warning("\n\n\npyfontaine is not available!"
               " You really MUST check the fonts with this tool."
               " To install it, see"
               " https://github.com/googlefonts"
               "/gf-docs/blob/master/ProjectChecklist.md#pyfontaine\n\n\n")


def check_glyphset_google_cyrillic_historical(fb, font_file):
  fb.new_check("132", "Checking Cyrillic Historical glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_cyrillic_historical")


def check_glyphset_google_cyrillic_plus(fb, font_file):
  fb.new_check("133", "Checking Google Cyrillic Plus glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_cyrillic_plus")


def check_glyphset_google_cyrillic_plus_locl(fb, font_file):
  fb.new_check("134", "Checking Google Cyrillic Plus"
                      " (Localized Forms) glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_cyrillic_plus_locl")


def check_glyphset_google_cyrillic_pro(fb, font_file):
  fb.new_check("135", "Checking Google Cyrillic Pro glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_cyrillic_pro")


def check_glyphset_google_greek_ancient_musical(fb, font_file):
  fb.new_check("136", "Checking Google Greek Ancient"
                      " Musical Symbols glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_greek_ancient_musical_symbols")


def check_glyphset_google_greek_archaic(fb, font_file):
  fb.new_check("137", "Checking Google Greek Archaic glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_greek_archaic")


def check_glyphset_google_greek_coptic(fb, font_file):
  fb.new_check("138", "Checking Google Greek Coptic glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_greek_coptic")


def check_glyphset_google_greek_core(fb, font_file):
  fb.new_check("139", "Checking Google Greek Core glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_greek_core")


def check_glyphset_google_greek_expert(fb, font_file):
  fb.new_check("140", "Checking Google Greek Expert glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_greek_expert")


def check_glyphset_google_greek_plus(fb, font_file):
  fb.new_check("141", "Checking Google Greek Plus glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_greek_plus")


def check_glyphset_google_greek_pro(fb, font_file):
  fb.new_check("142", "Checking Google Greek Pro glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_greek_pro")


def check_glyphset_google_latin_core(fb, font_file):
  fb.new_check("143", "Checking Google Latin Core glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_latin_core")


def check_glyphset_google_latin_expert(fb, font_file):
  fb.new_check("144", "Checking Google Latin Expert glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_latin_expert")


def check_glyphset_google_latin_plus(fb, font_file):
  fb.new_check("145", "Checking Google Latin Plus glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_latin_plus")


def check_glyphset_google_latin_plus_optional(fb, font_file):
  fb.new_check("146", "Checking Google Latin Plus"
                      " (Optional Glyphs) glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_latin_plus_optional")


def check_glyphset_google_latin_pro(fb, font_file):
  fb.new_check("147", "Checking Google Latin Pro glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_latin_pro")


def check_glyphset_google_latin_pro_optional(fb, font_file):
  fb.new_check("148", "Checking Google Latin Pro"
                      " (Optional Glyphs) glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_latin_pro_optional")


def check_glyphset_google_arabic(fb, font_file):
  fb.new_check("149", "Checking Google Arabic glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_arabic")


def check_glyphset_google_vietnamese(fb, font_file):
  fb.new_check("150", "Checking Google Vietnamese glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_vietnamese")


def check_glyphset_google_extras(fb, font_file):
  fb.new_check("151", "Checking Google Extras glyph coverage")
  check_with_pyfontaine(fb, font_file, "google_extras")
