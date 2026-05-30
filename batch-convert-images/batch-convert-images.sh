#!/bin/bash

TEXTDOMAIN="batch-convert-images@badmotorfinger"
TEXTDOMAINDIR="${HOME}/.local/share/locale"

# Images

_IMAGE__TITLE=$"Batch Convert Images"
_IMAGE__PROMPT=$"Choose the format to convert ALL selected files to:"
_IMAGE__COLUMN_1=$"Select"
_IMAGE__COLUMN_2=$"Format"
_IMAGE__COLUMN_3=$"Description"

_PROGRESS_TITLE=$"Batch Converting Images"
_PROGRESS_TEXT=$"Processing..."
_NOT_AN_IMAGE=$"is not an image file and will be skipped"

IMAGE__TITLE="$(/usr/bin/gettext "$_IMAGE__TITLE")"
IMAGE__PROMPT="$(/usr/bin/gettext "$_IMAGE__PROMPT")"
IMAGE__COLUMN_1="$(/usr/bin/gettext "$_IMAGE__COLUMN_1")"
IMAGE__COLUMN_2="$(/usr/bin/gettext "$_IMAGE__COLUMN_2")"
IMAGE__COLUMN_3="$(/usr/bin/gettext "$_IMAGE__COLUMN_3")"

PROGRESS_TITLE="$(/usr/bin/gettext "$_PROGRESS_TITLE")"
PROGRESS_TEXT="$(/usr/bin/gettext "$_PROGRESS_TEXT")"
NOT_AN_IMAGE="$(/usr/bin/gettext "$_NOT_AN_IMAGE")"

_NOT_A_PDF=$"is not a valid PDF file and will be skipped"

NOT_A_PDF="$(/usr/bin/gettext "$_NOT_A_PDF")"

# i removed the raw formats bc as far as i know you can not convert from other formats
# to raw formats (the reverse operation is possible) right? RIGHT? 😢
# + raw, arw, cr, cr2, nef, orf, sr2, rw2, nrw, k25, 3fr
#
# other formats need a more complex script so i removed them from the selection:
# FALSE "eps" "Encapsulated PostScript" \
# FALSE "ai" "Adobe Illustrator Document" \
# FALSE "tga" "Targa Image File" \
# FALSE "hdr" "High Dynamic Range Image" \
# FALSE "pcx" "PC Paintbrush Bitmap Image" \
# FALSE "psd" "Photoshop Document" \

# Get target format from user once for all files
if ! EXTENSION=$(
  /usr/bin/zenity --list --radiolist \
    --title="$IMAGE__TITLE" \
    --text="$IMAGE__PROMPT" \
    --height=320 \
    --width=640 \
    --column="$IMAGE__COLUMN_1" --column="$IMAGE__COLUMN_2" --column="$IMAGE__COLUMN_3" \
    FALSE "apng" "Animated Portable Network Graphics" \
    FALSE "avif" "AV1 Image File Format" \
    FALSE "bmp" "Bitmap" \
    FALSE "cur" "Microsoft Icon" \
    FALSE "gif" "Graphics Interchange Format" \
    FALSE "heic" "High Efficiency Image Coding" \
    FALSE "heif" "High Efficiency Image Format" \
    FALSE "ico" "Microsoft Icon" \
    FALSE "j2k" "JPEG 2000 Code Stream" \
    FALSE "jfi" "JPEG (Joint Photographic Experts Group)" \
    FALSE "jfif" "JPEG (Joint Photographic Experts Group)" \
    FALSE "jif" "JPEG (Joint Photographic Experts Group)" \
    FALSE "jp2" "JPEG 2000 Image" \
    FALSE "jpe" "JPEG (Joint Photographic Experts Group)" \
    FALSE "jpeg" "JPEG (Joint Photographic Experts Group)" \
    FALSE "jpg" "JPEG (Joint Photographic Experts Group)" \
    FALSE "pjp" "JPEG (Joint Photographic Experts Group)" \
    FALSE "pjpeg" "JPEG (Joint Photographic Experts Group)" \
    FALSE "pdf" "Portable Document Format" \
    FALSE "png" "Portable Network Graphics" \
    FALSE "svg" "plaintext Scalable Vector Graphics" \
    FALSE "svgz" "compressed Scalable Vector Graphics" \
    FALSE "tif" "Tagged Image File Format" \
    FALSE "tiff" "Tagged Image File Format" \
    FALSE "webp" "Web Picture format"
); then
  exit
fi

convert_image() {
  local FILE="$1"
  local DIRECTORY=$(dirname "$FILE")
  
  if [[ "${FILE##*.}" == "psd" ]]; then
    /usr/bin/convert "${FILE}[0]" -set filename:basename "%[basename]" "${DIRECTORY}/%[filename:basename].${EXTENSION}"
  elif [[ "${FILE##*.}" == "gif" ]]; then
    /usr/bin/convert "$FILE" -set filename:basename "%[basename]" "${DIRECTORY}/%[filename:basename]_frame_%05d.${EXTENSION}"
  elif [[ "${FILE##*.}" == "svg" && ("$EXTENSION" == "eps" || "$EXTENSION" == "pdf" || "$EXTENSION" == "png" || "$EXTENSION" == "ps" || "$EXTENSION" == "svg") ]]; then
    /usr/bin/rsvg-convert --format="$EXTENSION" --output="${FILE%.*}.${EXTENSION}" "$FILE"
  else
    /usr/bin/convert "$FILE" -set filename:basename "%[basename]" "${DIRECTORY}/%[filename:basename].${EXTENSION}"
  fi
}

convert_pdf() {
  local file="$1"
  local DIRECTORY=$(dirname "$file")
  
  if [ -z "$file" ]; then
    echo "Error: File argument is required."
    return 1
  fi

  # Use default settings for batch processing
  local format="png"
  local resolution="300"
  local firstpage="1"
  local lastpage
  
  # Calculate last page
  lastpage=$(pdfinfo "$file" | grep '^Pages:' | awk '{print $2}')

  # Create directory based on the filename
  local FILE_NAME=$(basename "$file" .pdf)
  [ ! -d "${DIRECTORY}/images_${FILE_NAME}" ] && mkdir -pv "${DIRECTORY}/images_${FILE_NAME}"

  # Determine format options based on target extension
  local format_options
  case "$EXTENSION" in
  "jpg"|"jpeg") format_options="-jpeg" ;;
  "png") format_options="-png" ;;
  "tiff"|"tif") format_options="-tiff" ;;
  *)
    format_options="-png"
    ;;
  esac

  pdftoppm \
    "${format_options}" \
    -forcenum \
    -sep _ \
    -r "$resolution" \
    -f "$firstpage" \
    -l "$lastpage" \
    "$file" \
    "${DIRECTORY}/images_${FILE_NAME}/pg"
}

# Special case: if creating animated GIF from multiple images
if [ "$EXTENSION" == "gif" ] && [ $# -gt 1 ]; then
  FIRST_FILE="$1"
  DIRECTORY=$(dirname "$FIRST_FILE")
  (
    /usr/bin/convert -delay 20 -loop 0 "$@" "${DIRECTORY}/output.gif"
  ) | /usr/bin/zenity --progress \
    --title="$PROGRESS_TITLE" \
    --text="$PROGRESS_TEXT" \
    --pulsate \
    --auto-close
  exit 0
fi

(
  TOTAL_FILES=$#
  COUNT=0
  for FILE in "$@"; do
    MIMETYPE=$(/usr/bin/file --mime-type -b "$FILE")
    if [[ $MIMETYPE == image/* ]]; then
      convert_image "$FILE"
      COUNT=$((COUNT + 1))
      echo "$((COUNT * 100 / TOTAL_FILES))"
      echo "# Converting $FILE ($COUNT of $TOTAL_FILES)"
    elif [[ $MIMETYPE == application/pdf ]]; then
      convert_pdf "$FILE"
      COUNT=$((COUNT + 1))
      echo "$((COUNT * 100 / TOTAL_FILES))"
      echo "# Converting $FILE ($COUNT of $TOTAL_FILES)"
    else
      [[ $MIMETYPE == image/* ]] && /usr/bin/zenity --warning --text="$FILE $NOT_AN_IMAGE."
      [[ $MIMETYPE == application/pdf ]] && /usr/bin/zenity --warning --text="$FILE $NOT_A_PDF."
    fi
  done
) | /usr/bin/zenity --progress \
  --title="$PROGRESS_TITLE" \
  --text="$PROGRESS_TEXT" \
  --percentage=0 \
  --auto-close
