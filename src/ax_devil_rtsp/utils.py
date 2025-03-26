import xml.etree.ElementTree as ET
import logging

logger = logging.getLogger("ax-devil-rtsp.utils")

def parse_metadata_xml(xml_data: bytes) -> dict:
    """
    Parse ONVIF metadata XML and extract relevant information.
    
    Args:
        xml_data: Raw XML bytes data
        
    Returns:
        dict: Parsed metadata information
    """
    try:
        try:
            xml_text = xml_data.decode('utf-8')
        except UnicodeDecodeError:
            xml_text = xml_data.decode('utf-8', errors='ignore')
            
        root = ET.fromstring(xml_text)
        result = {
            'objects': [],
            'utc_time': None,
            'raw_xml': xml_text
        }
        
        ns = {
            "tt": "http://www.onvif.org/ver10/schema",
            "bd": "http://www.onvif.org/ver20/analytics/humanbody"
        }
        
        # Extract objects
        for obj in root.findall('.//tt:Object', ns):
            obj_id = obj.get('ObjectId')
            type_elem = obj.find('.//tt:Type', ns)
            if type_elem is not None:
                result['objects'].append({
                    'id': obj_id,
                    'type': type_elem.text
                })
                
        # Extract frame time
        for frame in root.findall('.//tt:Frame', ns):
            utc_time = frame.get('UtcTime')
            if utc_time:
                result['utc_time'] = utc_time
                break
                
        return result
        
    except ET.ParseError as e:
        logger.error("XML Parse Error: %s", e)
        return None 