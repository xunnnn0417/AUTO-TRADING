"""Encode only the phone URL locally using the existing OpenCV dependency."""
from PySide6.QtGui import QImage


def phone_qr_image(origin):
    from .remote_control import normalized_origin
    import cv2
    text = normalized_origin(origin)
    matrix = cv2.QRCodeEncoder_create().encode(text)
    matrix = cv2.copyMakeBorder(matrix, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
    scale = max(1, 232 // matrix.shape[0])
    matrix = cv2.resize(matrix, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    return QImage(matrix.data, matrix.shape[1], matrix.shape[0],
                  matrix.strides[0], QImage.Format_Grayscale8).copy()
