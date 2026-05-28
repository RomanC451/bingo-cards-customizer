from bingo_cards.grid.placement import (
    build_default_grid_cells,
    build_uniform_grid_cells,
)


def test_build_default_grid_cells_count_and_bounds():
    cells = build_default_grid_cells(800, 1000, 5)
    assert len(cells) == 25
    for cell in cells:
        assert cell["width"] >= 20
        assert cell["height"] >= 20
        assert cell["x2"] > cell["x1"]
        assert cell["y2"] > cell["y1"]
        assert cell["center_x"] == cell["x1"] + cell["width"] // 2


def test_build_default_grid_cells_small_image_uses_minimum_margins():
    cells = build_default_grid_cells(100, 100, 3)
    assert len(cells) == 9
    assert min(cell["x1"] for cell in cells) >= 20


def test_build_uniform_grid_cells_clamps_cell_size():
    cells = build_uniform_grid_cells(3, 10, 20, 5, 5)
    assert cells[0]["width"] == 20
    assert cells[0]["height"] == 20
    assert len(cells) == 9


def test_build_uniform_grid_cells_positions():
    cells = build_uniform_grid_cells(2, 100, 200, 50, 60)
    by_rc = {(c["row"], c["col"]): c for c in cells}
    assert by_rc[(0, 0)]["x1"] == 100
    assert by_rc[(0, 1)]["x1"] == 150
    assert by_rc[(1, 0)]["y1"] == 260
