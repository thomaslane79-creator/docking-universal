// Exercise the pinned fork's real embedded-library loader and dispatch host.
// This intentionally does not substitute the runtime-source probe's host.
#include "metal_context.h"
#include <cmath>
#include <iostream>

int main() {
    MetalContext& ctx = MetalContext::instance();
    auto pipeline = ctx.makePipeline("scalar_mult");
    auto buffer = ctx.newBuffer(128 * sizeof(float));
    auto values = static_cast<float*>(ctx.bufferContents(buffer));
    for (unsigned i = 0; i < 128; ++i) values[i] = float(i) - 64;
    float factor = 2.75f;
    unsigned n = 128;
    MetalArg args[] = {MetalArg::fromBuffer(buffer),
                       MetalArg::fromBytes(&factor, sizeof(factor)),
                       MetalArg::fromBytes(&n, sizeof(n))};
    ctx.dispatch1D(pipeline, args, 3, n);
    float error = 0;
    for (unsigned i = 0; i < n; ++i) {
        float delta = std::abs(values[i] - (float(i) - 64) * factor);
        if (!std::isfinite(delta)) return 2;
        error = std::max(error, delta);
    }
    MetalContext::releaseBuffer(buffer);
    MetalContext::releasePipeline(pipeline);
    std::cout << "host_scalar_max_abs_error=" << error << "\n";
    return error > 1e-4f ? 1 : 0;
}
