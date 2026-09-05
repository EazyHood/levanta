"""Weights go from the file straight to the GPU; the host never holds the 4.6 GB.

On this 32 GB laptop with other applications open the standard path (build the network on
the CPU, then load) died twice with "OS error 1455: the paging file is too small" at the
DINOv2 build.  The direct path builds the network on the meta device and fills it from the
safetensors file on the target device.  safetensors stores a shared tensor once, so every
alias of a tied weight must be filled too (MapAnything has 60 tied groups, 76 alias names).

Thresholds written before the fix ran: after loading, no parameter or buffer is left on
the meta device, aliases share one tensor, and the values are the checkpoint's.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from levanta.recon.mapanything import fill_tied_aliases, load_from_state_dict_on_meta  # noqa: E402


class Tied(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.proj = torch.nn.Linear(4, 4, bias=False)
        self.alias = self.proj  # a second name for the same weights
        self.register_buffer("scale", torch.ones(1))


def test_aliases_are_filled_and_nothing_stays_on_meta():
    sd = {"proj.weight": torch.full((4, 4), 2.0), "scale": torch.tensor([3.0])}  # what safetensors keeps
    with torch.device("meta"):
        model = Tied()
    assert fill_tied_aliases(model, sd) == 1 and torch.equal(sd["alias.weight"], sd["proj.weight"])
    model = load_from_state_dict_on_meta(model, sd)
    assert not any(t.is_meta for t in list(model.parameters()) + list(model.buffers()))
    assert model.alias.weight is model.proj.weight
    assert float(model.proj.weight.detach().sum()) == 32.0 and float(model.scale) == 3.0


def test_a_checkpoint_that_does_not_cover_the_model_is_refused():
    with torch.device("meta"):
        model = Tied()
    with pytest.raises(RuntimeError):
        load_from_state_dict_on_meta(model, {"proj.weight": torch.zeros(4, 4)})  # no "scale"
