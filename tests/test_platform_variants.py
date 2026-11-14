from unittest.mock import Mock

import pytest

from fox3d.platform import Platform


@pytest.mark.parametrize("count", [None, 3])
def test_variants_returns_rd_result_and_forwards_arguments(tmp_path, count):
    platform = Platform(root=tmp_path, mock_blender=True)
    result = {"variants": [{"id": "variant-1"}]}
    platform.rd.run = Mock(return_value=result)

    kwargs = {} if count is None else {"count": count}
    assert platform.variants("product-1", tenant_id="tenant-1", **kwargs) is result
    platform.rd.run.assert_called_once_with(
        tenant_id="tenant-1",
        text="variant of product-1",
        variant_count=12 if count is None else count,
    )
