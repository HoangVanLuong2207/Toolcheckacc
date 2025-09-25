from flask import Flask, render_template, request, jsonify, send_from_directory
import os
from werkzeug.utils import secure_filename
import subprocess
import json
import traceback
import logging
import time

# Cấu hình logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Tạo thư mục upload nếu chưa tồn tại
try:
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    logger.info(f"Đã tạo thư mục upload: {app.config['UPLOAD_FOLDER']}")
except Exception as e:
    logger.error(f"Lỗi khi tạo thư mục upload: {str(e)}")
    raise

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/check_accounts', methods=['POST'])
def check_accounts():
    logger.info("Nhận được yêu cầu kiểm tra tài khoản")
    
    try:
        if 'file' not in request.files:
            logger.warning("Không có file trong yêu cầu")
            return jsonify({'status': 'error', 'message': 'Không có file được tải lên'}), 400
        
        file = request.files['file']
        if file.filename == '':
            logger.warning("Tên file trống")
            return jsonify({'status': 'error', 'message': 'Không có file được chọn'}), 400
        
        logger.info(f"Đang xử lý file: {file.filename}")
        
        try:
            # Đọc nội dung file
            content = file.read().decode('utf-8')
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            logger.info(f"Đã đọc được {len(lines)} dòng từ file")
            
            if not lines:
                raise ValueError("File không có nội dung")
            
            # Đường dẫn đến file accounts.txt
            accounts_file = os.path.join(os.getcwd(), 'accounts.txt')
            logger.info(f"Đang ghi dữ liệu vào: {accounts_file}")
            
            # Xử lý từng dòng và ghi vào accounts.txt
            valid_accounts = 0
            with open(accounts_file, 'w', encoding='utf-8') as f:
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                        
                    # Giữ nguyên định dạng username:password
                    if ':' in line:
                        # Kiểm tra xem có đúng định dạng username:password không
                        parts = line.split(':', 1)
                        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                            f.write(f"{line}\n")
                            valid_accounts += 1
                        else:
                            logger.warning(f"Dòng không hợp lệ (thiếu username hoặc mật khẩu): {line}")
                    else:
                        logger.warning(f"Dòng không có định dạng username:password: {line}")
            
            if valid_accounts == 0:
                raise ValueError("Không tìm thấy tài khoản hợp lệ trong file")
                
            logger.info(f"Đã ghi {valid_accounts} tài khoản vào accounts.txt, bắt đầu kiểm tra")
            
            # Gọi check_garena.py thông qua terminal
            import subprocess
            import sys
            
            # Tạo lệnh để chạy trong terminal mới
            if sys.platform == 'win32':
                # Trên Windows, sử dụng start để mở terminal mới
                command = f'start cmd /k "cd /d {os.getcwd()} && python check_garena.py --headless"'
                subprocess.Popen(command, shell=True)
            else:
                # Trên macOS/Linux
                command = f'gnome-terminal -- python3 {os.path.join(os.getcwd(), "check_garena.py")} --headless'
                subprocess.Popen(command, shell=True, executable='/bin/bash')
            
            logger.info("Đã khởi chạy check_garena.py trong terminal mới")
            return jsonify({
                'status': 'success',
                'message': 'Đã bắt đầu kiểm tra tài khoản trong terminal mới. Vui lòng kiểm tra cửa sổ terminal vừa mở.'
            })
            
        except Exception as e:
            error_msg = f"Lỗi khi xử lý file: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            return jsonify({
                'status': 'error',
                'message': error_msg,
                'details': str(e)
            }), 500
            
    except Exception as e:
        error_msg = f"Lỗi không xử lý được: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': error_msg,
            'details': str(e)
        }), 500

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory('.', filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
