import opengraph
from pelican import signals # For making this plugin work with Pelican.
import re # For using regular expressions.
import unicodedata
import os
import codecs
import json
import metadata_parser
import requests
import shutil
import PIL
import uuid
import pdb
from urllib.parse import urljoin

img_content_types = {
    "image/jpeg" : "jpg",
    "image/png" : "png",
    "image/gif" : "gif",
    "image/jpg" : "jpg"
}


# Helper routine to enable us to save urls as filenames.
def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('utf-8')
    value = re.sub('[^\w\s-]', '', value).strip().lower()
    value = re.sub('[-\s]+', '-', value)

    return value

# Called once when the plugin starts. Use this to initialize directories.
def init(pelican_data):
    images_path = os.path.join(pelican_data.settings["PATH"], "images")
    thumbnail_cache = os.path.join(images_path, "thumbnails")
    if not os.path.exists(thumbnail_cache):
        os.mkdir(thumbnail_cache)

    cache = pelican_data.settings["CACHE_PATH"]
    url_cache = os.path.join(cache, "urlcard_ogcache")

    # Account for /cache being created, but urlcard_ogcache not existing.
    if not os.path.exists(cache):
        os.mkdir(cache)
        if not os.path.exists(url_cache):
            os.mkdir(url_cache)
    else:
        if not os.path.exists(url_cache):
            os.mkdir(url_cache)

# Let's get a URL that's on a line by itself. For each of these lines, we'll get the OpenGraph data for the URL,
# and use that to generate a Medium-style "card" for the URL inline using Bootstrap's
def create_url_card(pelican_data):
    if pelican_data._content:
        post_page_data = pelican_data._content
    else:
        return

    # Construct variables for paths.
    images_path = os.path.join(pelican_data.settings["PATH"], "images")
    thumbnail_cache = os.path.join(images_path, "thumbnails")
    cache = pelican_data.settings["CACHE_PATH"]
    url_cache = os.path.join(cache, "urlcard_ogcache")

    # Get location of default pelican card image (e.g., a version of the site logo).
    # If not set in pelicanconf.py, die.
    if "URL_CARD_DEFAULT_IMG" in pelican_data.settings:
        default_img = pelican_data.settings["URL_CARD_DEFAULT_IMG"]
    else:
        raise ValueError("ERROR: URL_CARD_DEFAULT_IMG not set in pelicanconf.py. Please add a setting for this if you wish to use the URL Card extension; it is used to add an image to a card when none is found in the OpenGraph data retrieved from a Web site.")

    pelican_data._content = create_url_card_from_text(post_page_data, thumbnail_cache, url_cache, default_img)

def create_url_card_from_text(content, thumbnail_cache, url_cache, default_img):
    replaced_str = content

    all_urls = re.findall("<p>https?:\/\/.*?</p>", content, re.DOTALL)
    if len(all_urls) == 0:
        return content

    #pdb.set_trace()
    for url in all_urls:
        # Strip <P> tags that Pelican inserts from HTML generation.
        # We could have done this with memory parens in the regexp, but we want to replace the URL
        # and the <P> tags below.
        clean_url = re.sub('<[^<]+?>', '', url)

        #if clean_url == "https://shinbun20.com/oiwai/fushime/birthday/yurai-tanjyobi/":
        #    pdb.set_trace()

        # Check to see if we've retrieved this URL before and saved its opengraph data.
        slugified_url = slugify(clean_url)
        url_og_cache = os.path.join(url_cache, (".".join([slugified_url, "json"])))
        if os.path.exists(url_og_cache):
            # pdb.set_trace()
            with codecs.open(url_og_cache, 'r', 'utf-8-sig') as f:
                og = json.load(f)
        else:
            print("Retrieving OpenGraph data for {} for the first time - expect a small delay...".format(clean_url))
            # Get OG data. Strip HTML from the tags.
            page = metadata_parser.MetadataParser(url=clean_url, search_head_only=True)
            og = page.metadata["og"]

            # Some sites won't expose this data. E.g., Wikipedia JP only returns og:image.
            # Put in reasonable defaults, or dig out a better option (e.g., title) from BeautifulSoup.
            if "description" not in og:
                og["description"] = ""
            if "title" not in og:
                if page.soup.title:
                    og["title"] = page.soup.title.string
                else:
                    og["title"] = "(No Title)"
            if "url" not in og:
                og["url"] = clean_url

            # Detect if there's an image keyword - some feeds will actually not have one.
            # In this case, we want to fail gracefully with a message, and inject a default graphic.
            if "image" not in og:
                print("WARNING: Image not found for URL {}. Saving OpenGraph data with the default URL card image {}. You can change the cached Opengraph data manually if you want to use a different image.".format(url, default_img))
                og["image"] = default_img

            # Download images for the first image found in the Opengraph to disk.
            # We will use these to generate thumbnail links.
            if isinstance(og["image"], list):
                img_url = og["image"][0]
            else:
                img_url = og["image"]
            # Account for the use of relative image URLs.
            img_url = urljoin(clean_url, img_url)

            img_save_dir = os.path.join(thumbnail_cache, slugified_url)
            if not os.path.exists(img_save_dir):
                os.mkdir(img_save_dir)
            #img_save_filename = os.path.join(img_save_dir, img_url.rsplit("/", 1))

            #pdb.set_trace()
            img_ext = None
            while img_ext is None:
                response = requests.get(img_url, stream=True)

                #!FIX: On rare occasions, no content-type is returned, so use the URL suffix.
                # If that's not available, then give up and use the default image.
                #!FIX: Some valid types (e.g., PNG) come through as "binary/octet-stream". Detect this and use extension logic.
                #!TODO: Can we detect type from the stream?!
                if not "Content-Type" in response.headers or ("Content-Type" in response.headers and response.headers["Content-Type"].lower() == "binary/octet-stream"):
                    content_type = img_url.split(".")[-1].lower()
                    if content_type not in img_content_types.values():
                        print("Unsupported image type - no Content-Type, and extension provides no clues as to image source. Use default image.")
                    else:
                        print("No Content-Type found in image retrieval, but valid extension on URL found. URL: {}. Image type: {}".format(img_url, content_type))
                        img_ext = content_type
                else:
                    content_type = response.headers["Content-Type"]

                    if content_type not in img_content_types:
                        print("Image URL has a content type we don't recognize. We will use the default image instead. Image: {}; URL: {}".format(img_url, clean_url))
                        img_url = default_img
                    else:
                        img_ext = img_content_types[content_type]

            # Use the content type to get an extension, and assign a GUID image name.
            # This prevents us from having to guess at and/or unmangle complicated URLs.
            unique_id = str(uuid.uuid4())
            filename = ".".join([unique_id, img_ext])

            relative_img_url = "/".join(["images", filename])
            img_save_filename = os.path.join(img_save_dir, filename)
            with open(img_save_filename, 'wb') as out_file:
                response.raw.decode_content = True
                shutil.copyfileobj(response.raw, out_file)
            del response

            # Now let's create a scaled thumbnail.
            thumb_unique_id = "-".join([unique_id, "thumbnail"])
            thumb_filename = ".".join([thumb_unique_id, img_ext])
            thumb_save_path = os.path.join(img_save_dir, thumb_filename)
            img_obj = PIL.Image.open(img_save_filename)
            maxsize = (200, 300)
            img_obj.thumbnail(maxsize, PIL.Image.ANTIALIAS)

            # If the image has a height greater than 200px, crop from the center.
            width,height = img_obj.size
            # pdb.set_trace()
            if height > 200:
                 final_img = img_obj.crop((width // 2 - width // 2, height // 2 - 200 // 2, width // 2 + width // 2, height // 2 + 200 // 2))
            else:
                final_img = img_obj

            print("Saving URL thumbnail image to {}".format(thumb_save_path))
            final_img.save(thumb_save_path)

            # Save the save information for the thumbnail into our OpenGraph data as root relative URL.
            relative_thumb_url = "/".join(["images", "thumbnails", slugified_url, thumb_filename])
            og["pelican:thumbnail_image"] = relative_thumb_url

            # Dump the dict to disk - save all og metadata.
            with codecs.open(url_og_cache, 'w', 'utf-8-sig') as f:
                json.dump(og, f)

        # Create the card HTML.
        # If we're dealing with a video, embed it.
        if "video:url" in og:
            # Find the embed URL.
            #!TODO: What if there is none??
            #!TODO: Difference between secure_url and url?
            #!TODO: Do other video sites use this "embed" syntax? If not, need to find out what they do.
            embed_url = ""
            if isinstance(og["video:url"], str):
                embed_url = og["video:url"]
            else:
                for find_embed_url in og["video:url"]:
                    if "embed" in find_embed_url:
                        embed_url = find_embed_url

            card_html = '''
<div class="embed-responsive embed-responsive-16by9 col-xs-12 text-center">
<iframe
src="%s"
frameborder="0"
allow="autoplay; encrypted-media"
allowfullscreen
class="embed-responsive-item"
></iframe>
</div>
<p/>
''' % (embed_url)

        else:
            # Assume it's an article.

            card_html = '''
    <center>

    <div class="media border" style="padding:5px;">
    <a href="%s">
      <img class="mr-3 lazy" data-src="/%s"></a>
      <div class="media-body text-left">
        <h5 class="mt-0 text-left">%s</h5>

        <div style="padding-top:8px;padding-bottom:8px;" class="text-left"><small>%s</small></div>

        <div><em><a href="%s">Link to Source</a></em></div>
      </div>
    </div>
    </center>
    <p/>

    ''' % (og["url"], og["pelican:thumbnail_image"], og["title"], og["description"], og["url"])

        # now replace URL with our HTML.
        replaced_str = replaced_str.replace(url, card_html)

    return replaced_str

def register():
    signals.content_object_init.connect(create_url_card)
    signals.initialized.connect(init)
