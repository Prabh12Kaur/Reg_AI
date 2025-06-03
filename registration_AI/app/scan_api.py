from flask import Flask, request, jsonify
from flask_cors import CORS
from pyaadhaar.decode import AadhaarSecureQr
import json
import xml.etree.ElementTree as ET

app = Flask(__name__)
CORS(app)

@app.route('/parse_qr', methods=['POST'])
def parse_qr():
    qr_data = request.json.get('qrData', '').strip()

    # 1. Secure QR
    try:
        secure = AadhaarSecureQr(qr_data)
        data = secure.decodeddata()
        address = ", ".join(filter(None, [
            data.get("house"), data.get("street"), data.get("vtc"),
            data.get("subdistrict"), data.get("district"),
            data.get("state"), data.get("pincode")
        ]))
        return jsonify({
            "source": "secure",
            "name": data.get("name"),
            "dob": data.get("dob"),
            "gender": data.get("gender"),
            "address": address
        })
    except Exception as e:
        print("Secure QR Decode Error:", e)

    # 2. Plain XML
    try:
        if qr_data.strip().startswith("<"):
            xml_root = ET.fromstring(qr_data)
            data = xml_root.attrib
            address = ", ".join(filter(None, [
                data.get("house"), data.get("loc"), data.get("vtc"),
                data.get("dist"), data.get("state"), data.get("pc")
            ]))
            return jsonify({
                "source": "plain",
                "name": data.get("name"),
                "dob": data.get("dob", data.get("yob")),
                "gender": data.get("gender"),
                "address": address
            })
    except Exception as e:
        print("Plain XML QR Decode Error:", e)

    # 3. ABHA
    try:
        abha = json.loads(qr_data)
        address = abha.get("address", "")
        return jsonify({
            "source": "abha",
            "name": abha.get("name"),
            "dob": abha.get("dob"),
            "gender": abha.get("gender"),
            "address": address
        })
    except Exception as e:
        print("ABHA QR Decode Error:", e)

    return jsonify({'error': 'Unsupported or invalid QR data'}), 400

if __name__ == '__main__':
    app.run(debug=True)
