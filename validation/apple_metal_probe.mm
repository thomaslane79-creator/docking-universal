// Isolated synthetic kernel test, not a docking engine or speed benchmark.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <simd/simd.h>
#include <cmath>
#include <cstdio>
#include <stdexcept>

struct NoncacheArgs {
    uint32_t movable, receptor; float cutoffSq, slope;
    float bx, by, bz; uint32_t numc; float ex, ey, ez; uint32_t pad;
};
struct SplineInfo { uint32_t n; float fraction, cutoff; uint32_t pad; };
static_assert(sizeof(NoncacheArgs) == 48);
static_assert(sizeof(SplineInfo) == 16);

static float difference(float actual, float expected) {
    if (!std::isfinite(actual) || !std::isfinite(expected))
        throw std::runtime_error("Non-finite GPU or reference value");
    return fabsf(actual-expected);
}

static id<MTLBuffer> buffer(id<MTLDevice> device, const void* data, NSUInteger size) {
    auto result = [device newBufferWithLength:size options:MTLResourceStorageModeShared];
    if (!result) throw std::runtime_error("Metal buffer allocation failed");
    if (data) memcpy(result.contents, data, size);
    else memset(result.contents, 0, size);
    return result;
}

static id<MTLComputePipelineState> pipeline(id<MTLDevice> device, id<MTLLibrary> library, NSString* name) {
    NSError* error = nil;
    auto function = [library newFunctionWithName:name];
    if (!function) throw std::runtime_error("Missing upstream kernel");
    auto result = [device newComputePipelineStateWithFunction:function error:&error];
    if (!result) throw std::runtime_error(error.localizedDescription.UTF8String);
    return result;
}

static void completed(id<MTLCommandBuffer> command) {
    [command commit]; [command waitUntilCompleted];
    if (command.status != MTLCommandBufferStatusCompleted)
        throw std::runtime_error(command.error.localizedDescription.UTF8String ?: "Metal command failed");
}

int main(int argc, char** argv) {
  @autoreleasepool {
    NSMutableDictionary* result = [@{@"scope": @"synthetic upstream Metal kernels, not docking",
                                   @"status": @"failed"} mutableCopy];
    int code = 1;
    try {
        if (argc != 2) throw std::runtime_error("Pass the pinned gnina_kernels.metal source path");
        auto device = MTLCreateSystemDefaultDevice();
        if (!device) throw std::runtime_error("No Metal GPU device available");
        result[@"device"] = device.name;
        result[@"unified_memory"] = @(device.hasUnifiedMemory);
        result[@"registry_id"] = @(device.registryID);
        NSError* error = nil;
        auto source = [NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]
                                               encoding:NSUTF8StringEncoding error:&error];
        if (!source) throw std::runtime_error(error.localizedDescription.UTF8String);
        // Runtime compilation avoids installing Apple's optional offline compiler.
        auto library = [device newLibraryWithSource:source options:nil error:&error];
        if (!library) throw std::runtime_error(error.localizedDescription.UTF8String);
        result[@"compiled_functions"] = library.functionNames;
        auto queue = [device newCommandQueue];
        if (!queue) throw std::runtime_error("No Metal command queue");
        auto scalar = pipeline(device, library, @"scalar_mult");
        constexpr uint32_t n = 128;
        float numbers[n];
        for (uint32_t i=0; i<n; ++i) numbers[i] = float(i)-64;
        auto values = buffer(device, numbers, sizeof(numbers));
        float factor = 2.75f;
        auto command = [queue commandBuffer];
        auto encoder = [command computeCommandEncoder];
        [encoder setComputePipelineState:scalar];
        [encoder setBuffer:values offset:0 atIndex:0];
        [encoder setBytes:&factor length:sizeof(factor) atIndex:1];
        [encoder setBytes:&n length:sizeof(n) atIndex:2];
        [encoder dispatchThreads:MTLSizeMake(n,1,1) threadsPerThreadgroup:MTLSizeMake(32,1,1)];
        [encoder endEncoding]; completed(command);
        float scalarError = 0;
        for (uint32_t i=0; i<n; ++i)
            scalarError = fmaxf(scalarError, difference(((float*)values.contents)[i], numbers[i]*factor));
        result[@"scalar_max_absolute_error"] = @(scalarError);
        result[@"scalar_gpu_seconds"] = @(command.GPUEndTime-command.GPUStartTime);
        if (scalarError > 1e-6f) throw std::runtime_error("Scalar GPU result mismatch");

        // Controlled spline E(r)=r^2: three heavy atoms and one ignored hydrogen.
        simd_float4 ligand[] = {{1,0,0,0},{-2,0,0,0},{7,0,0,0},{1,0,0,0}};
        simd_float4 receptor[] = {{0,0,0,0},{20,0,0,0}};
        uint32_t ligTypes[] = {2,2,2,1}, recTypes[] = {2,2};
        SplineInfo info[6]; uint32_t offsets[6] = {};
        for (auto& value: info) value = {1,10,8,0};
        float knots[] = {0,0,1,0,0};
        NoncacheArgs args = {4,2,64,10,-5,-5,-5,1,5,5,5,0};
        auto lig = buffer(device, ligand, sizeof(ligand));
        auto rec = buffer(device, receptor, sizeof(receptor));
        auto out = buffer(device, nullptr, sizeof(ligand));
        auto lt = buffer(device, ligTypes, sizeof(ligTypes));
        auto rt = buffer(device, recTypes, sizeof(recTypes));
        auto si = buffer(device, info, sizeof(info));
        auto sk = buffer(device, knots, sizeof(knots));
        auto so = buffer(device, offsets, sizeof(offsets));
        auto pairs = pipeline(device, library, @"noncache_pair_energy");
        command = [queue commandBuffer]; encoder = [command computeCommandEncoder];
        [encoder setComputePipelineState:pairs];
        [encoder setBytes:&args length:sizeof(args) atIndex:0];
        NSArray* buffers = @[lig,out,lt,rec,rt,si,sk,so];
        for (NSUInteger i=0; i<buffers.count; ++i) [encoder setBuffer:buffers[i] offset:0 atIndex:i+1];
        [encoder dispatchThreads:MTLSizeMake(4*256,1,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];
        [encoder endEncoding]; completed(command);
        simd_float4 expected[] = {{2,0,0,1},{-4,0,0,4},{14,0,0,49},{0,0,0,0}};
        float pairError = 0;
        for (int i=0; i<4; ++i) for (int j=0; j<4; ++j)
            pairError = fmaxf(pairError, difference(((simd_float4*)out.contents)[i][j], expected[i][j]));
        result[@"pair_energy_force_max_absolute_error"] = @(pairError);
        result[@"pair_gpu_seconds"] = @(command.GPUEndTime-command.GPUStartTime);
        if (pairError > 1e-4f) throw std::runtime_error("Pair-energy/force GPU result mismatch");

        auto total = buffer(device, nullptr, sizeof(float));
        auto post = pipeline(device, library, @"noncache_postprocess");
        float curl = 1000;
        command = [queue commandBuffer]; encoder = [command computeCommandEncoder];
        [encoder setComputePipelineState:post];
        [encoder setBytes:&args length:sizeof(args) atIndex:0];
        [encoder setBuffer:lig offset:0 atIndex:1];
        [encoder setBuffer:out offset:0 atIndex:2];
        [encoder setBytes:&curl length:sizeof(curl) atIndex:3];
        [encoder setBuffer:total offset:0 atIndex:4];
        [encoder dispatchThreads:MTLSizeMake(4,1,1) threadsPerThreadgroup:MTLSizeMake(4,1,1)];
        [encoder endEncoding]; completed(command);
        float postError = 0, expectedTotal = 0;
        for (int i=0; i<4; ++i) {
            float f = curl/(curl+expected[i].w);
            expected[i].x *= f*f; expected[i].w *= f;
            if (i==2) { expected[i].x += 10; expected[i].w += 20; }
            expectedTotal += expected[i].w;
            for (int j=0; j<4; ++j)
                postError = fmaxf(postError, difference(((simd_float4*)out.contents)[i][j], expected[i][j]));
        }
        float totalError = difference(((float*)total.contents)[0], expectedTotal);
        result[@"curl_bounds_force_max_absolute_error"] = @(postError);
        result[@"total_energy_absolute_error"] = @(totalError);
        if (postError > 1e-4f || totalError > 1e-4f)
            throw std::runtime_error("Postprocess GPU result mismatch");
        result[@"status"] = @"passed"; code = 0;
    } catch (const std::exception& e) { result[@"error"] = [NSString stringWithUTF8String:e.what()]; }
    NSData* json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];
    fwrite(json.bytes, 1, json.length, stdout); printf("\n"); return code;
  }
}
