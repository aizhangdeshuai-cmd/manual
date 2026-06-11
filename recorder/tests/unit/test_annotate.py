from pathlib import Path
from PIL import Image, ImageChops
from recorder_plugin.annotate import Annotation, annotate_image


def make_test_image(path: Path) -> Path:
    img = Image.new("RGB", (400, 300), color="white")
    img.save(path)
    return path


def test_annotate_box(tmp_path):
    src = make_test_image(tmp_path / "src.png")
    dst = tmp_path / "annotated.png"
    annotations = [Annotation(shape="box", x=10, y=20, w=100, h=50, label="Click")]
    annotate_image(src, dst, annotations)
    assert dst.exists()
    diff = ImageChops.difference(Image.open(src), Image.open(dst))
    assert diff.getbbox() is not None


def test_annotate_number(tmp_path):
    src = make_test_image(tmp_path / "src.png")
    dst = tmp_path / "annotated.png"
    annotations = [Annotation(shape="number", x=200, y=150, w=30, h=30, n=1)]
    annotate_image(src, dst, annotations)
    assert dst.exists()


def test_annotate_highlight(tmp_path):
    src = make_test_image(tmp_path / "src.png")
    dst = tmp_path / "annotated.png"
    annotations = [Annotation(shape="highlight", x=10, y=10, w=100, h=50, label="Note")]
    annotate_image(src, dst, annotations)
    assert dst.exists()


def test_annotate_arrow(tmp_path):
    src = make_test_image(tmp_path / "src.png")
    dst = tmp_path / "annotated.png"
    annotations = [Annotation(shape="arrow", from_xy=(20, 30), to_xy=(80, 100), label="to")]
    annotate_image(src, dst, annotations)
    assert dst.exists()


def test_annotate_composite(tmp_path):
    src = make_test_image(tmp_path / "src.png")
    dst = tmp_path / "annotated.png"
    annotations = [
        Annotation(shape="box", x=10, y=10, w=100, h=50, label="A"),
        Annotation(shape="arrow", from_xy=(20, 30), to_xy=(80, 100), label="to"),
        Annotation(shape="number", x=200, y=200, w=20, h=20, n=2),
    ]
    annotate_image(src, dst, annotations)
    assert dst.exists()


def test_annotate_no_annotations_passthrough(tmp_path):
    src = make_test_image(tmp_path / "src.png")
    dst = tmp_path / "annotated.png"
    annotate_image(src, dst, [])
    assert src.read_bytes() == dst.read_bytes()
