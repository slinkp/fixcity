from django.conf import settings
from django.contrib import comments
from django.contrib.contenttypes.models import ContentType
from django.utils.encoding import smart_unicode
from fixcity.bmabr.models import Rack
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image
from reportlab.platypus import PageBreak
from reportlab.platypus import Paragraph
from reportlab.platypus import SimpleDocTemplate
from reportlab.platypus import Spacer
from reportlab.platypus import Table
from reportlab.platypus import TableStyle
from voting.models import Vote

stylesheet = getSampleStyleSheet()
normalStyle = stylesheet['Normal']

Comment = comments.get_model()

def make_pdf(bulk_order, outfile):
    """
    Generates a PDF and writes it to file-like object `outfile`.
    """
    cb = bulk_order.communityboard
    date = bulk_order.date.replace(microsecond=0)
    doc = SimpleDocTemplate(outfile) 

    # XXX Sorting by street would be nice, but we don't have
    # addresses split into components, so we can't.
    racks = sorted(bulk_order.racks, key=lambda x: x.date)

    body = []

    body.append(make_rack_table(racks))

    for rack in racks:
        body.append(PageBreak())
        body.extend(make_rack_page(rack))
        break  # XXX
    doc.build(body)


def make_rack_table(racks):
    header = ['No.', 'Address', 'Date', 'Establishment',
              'Email', 'Verified?', 'Source']
    header = [Paragraph('<b>%s</b>' % s, normalStyle) for s in header]
    rows = [header]
    
    for rack in racks:
        verified = rack.verified and 'Y' or 'N'
        rows.append([str(rack.id),
                     Paragraph(rack.address, normalStyle),
                     rack.date.date(),
                     Paragraph(rack.title, normalStyle),
                     rack.email, verified, rack.source])

    rack_listing = Table(rows, 
                         colWidths=[25, 100, 55, 100, 120, 45, 40],
                         repeatRows=1)
    rack_listing.setStyle(TableStyle(
            [('ROWBACKGROUNDS', (0, 1), (-1, -1),
              [colors.white, colors.Color(0.9, 0.91, 0.96)],
              )]))
    return rack_listing


def make_rack_page(rack):
    # I suppose we 'should' use a PageTemplate and Frames and so
    # forth, but frankly I don't have enough time to learn Platypus
    # well enough to understand them.
    flowables = []
    flowables.append(Paragraph('%s. %s' % (rack.id, rack.title),
                               stylesheet['h1']))
    flowables.append(Paragraph(rack.address, stylesheet['h1']))
    from fixcity.bmabr.views import cross_streets_for_rack

    prev_street, next_street = cross_streets_for_rack(rack)
    prev_street = str(prev_street).title()
    next_street = str(next_street).title()
    flowables.append(Paragraph(
            'Cross Streets: %s and %s' % (prev_street, next_street),
            stylesheet['h2']))

    # Make a map image.
    # Derive the bounding box from rack center longitude/latitude.
    # The offset was arrived at empirically by guess-and-adjust.
    ratio = 0.65
    x_offset = 0.002
    y_offset = x_offset * ratio
    bounds = (rack.location.x - x_offset, rack.location.y - y_offset,
              rack.location.x + x_offset, rack.location.y + y_offset)
 
    image_pixels_x = 640  # That's the most google will give us.
    image_pixels_y = image_pixels_x * ratio

    image_inches_x = 3.5 * inch
    image_inches_y = image_inches_x * ratio

    tries = 3
    for i in range(tries):
        try:
            the_map = get_map(bounds, size=(image_pixels_x, image_pixels_y),
                              format='jpg')
        except RuntimeError:
            if i < tries:
                continue
            else:
                raise
    
    map_row = [Image(the_map, width=image_inches_x, height=image_inches_y)]

    # Photo, if provided.
    if rack.photo.name:
        # XXX Originals may be bigger than we need, and bloat the PDF.
        # Scale it down a bit?
        map_row.append(Image(rack.photo.path, width=image_inches_x,
                             height=image_inches_y))
    else:
        map_row.append(Paragraph('<i>no photo provided</i>', normalStyle))

    map_table = Table([map_row], colWidths=[image_inches_x + 0.25,
                                            image_inches_x + 0.25])
    flowables.append(map_table)
    flowables.append(Spacer(0, 0.25 * inch))
  
    flowables.append(Paragraph('Description', stylesheet['h1']))
    flowables.append(Paragraph(rack.description or 'none', normalStyle))

    votes = Vote.objects.get_score(rack)
    flowables.append(Spacer(0, 0.25 * inch))
    flowables.append(Paragraph('<b>%d likes</b>' % votes['score'], normalStyle))

    comment_count = Comment.objects.filter(
        content_type=ContentType.objects.get_for_model(rack),
        object_pk=smart_unicode(rack.pk), site__pk=settings.SITE_ID).count()

    flowables.append(Paragraph('<b>%d comments</b>' % comment_count, normalStyle))

    return flowables



def get_map(bbox, size=(400, 256), format='jpg'):
    """Generate a map given some bounding box.  Writes the image to file
    and returns the filename.  ReportLab reads the image given a filename
    during doc.build.  This file should be deleted after the doc is built.
    Perhaps this will be different with a PIL image.

    XXX would be nice to use our own tiles, but this was already working
    """
    # Originally copied from the old Almanac grok code,
    # http://svn.opengeo.org/almanac/siteapp/trunk/opengeo/almanac/pdf.py

    import urllib, httplib2, tempfile, os

    # GMap API Key for opengeo.org - static api doesn't care about origin
    # XXX need to make this configurable and probably get our own!!
    url = 'http://maps.google.com/staticmap'
    key = 'ABQIAAAAeDjUod8ItM9dBg5_lz0esxTnme5EwnLVtEDGnh-lFVzRJhbdQhQBX5VH8Rb3adNACjSR5kaCLQuBmw'

    center = ((bbox[2] + bbox[0]) / 2, (bbox[3] + bbox[1]) / 2)
    span = (bbox[2] - bbox[0], bbox[3] - bbox[1])
    
    params = {'center': '%f,%f' % (center[1], center[0]),
              'span': '%f,%f' % (span[1], span[0]),
              'size': '%dx%d' % (size[0], size[1]),
              'format': format,
              'key': key}    
    query = urllib.urlencode(params)
    url = "%s?%s" % (url, query)
    http = httplib2.Http('.cache', timeout=30)
    response, data = http.request(url)
    if response.status != 200:
        raise RuntimeError("Response %s while retrieving %s" % (response.status, url))
    # would be nice to deal directly with image data instead of writing first
    tmp, path = tempfile.mkstemp('.%s' % format)
    os.write(tmp, data)
    os.close(tmp)
    
    return path
