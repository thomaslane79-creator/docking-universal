// Diagnostic only: evaluate retained pair distances, never search or alter poses.
#define CL_SILENCE_DEPRECATION
#include <OpenCL/opencl.h>
#include <fstream>
#include <iostream>
#include <vector>
#include <stdexcept>
#include <string>
#include <cstring>

static void ok(cl_int status, const char* stage) {
    if (status != CL_SUCCESS) throw std::runtime_error(std::string(stage)+": "+std::to_string(status));
}

int main(int argc, char** argv) {
    try {
        if(argc!=5) throw std::runtime_error("input-float4-pairs output-float4 spacing pair-count");
        size_t count=std::stoull(argv[4]); float spacing=std::stof(argv[3]);
        std::ifstream input(argv[1],std::ios::binary|std::ios::ate);
        if(!input || size_t(input.tellg())!=count*8*sizeof(float)) throw std::runtime_error("Input size mismatch");
        input.seekg(0); std::vector<float> pairs(count*8), output(count*4);
        input.read(reinterpret_cast<char*>(pairs.data()),pairs.size()*sizeof(float));
        cl_platform_id platform; cl_device_id device;
        ok(clGetPlatformIDs(1,&platform,nullptr),"platform");
        ok(clGetDeviceIDs(platform,CL_DEVICE_TYPE_GPU,1,&device,nullptr),"GPU device");
        char name[512]={}; ok(clGetDeviceInfo(device,CL_DEVICE_NAME,sizeof(name),name,nullptr),"device name");
        std::cout<<"GPU: "<<name<<"\n";
        cl_int status; cl_context context=clCreateContext(nullptr,1,&device,nullptr,nullptr,&status);ok(status,"context");
        cl_command_queue queue=clCreateCommandQueue(context,device,0,&status);ok(status,"queue");
        const char* source=R"CL(
        __kernel void distances(__global const float4* coords, __global float4* output,
                                float spacing, uint count) {
            uint i=get_global_id(0); if(i>=count) return;
            float4 a=coords[2*i], b=coords[2*i+1];
            float subx=a.x-b.x, suby=a.y-b.y, subz=a.z-b.z;
            float squared=subx*subx+suby*suby+subz*subz;
            float native_distance=native_sqrt(squared)*spacing;
            output[i]=(float4)(native_distance,sqrt(squared)*spacing,squared,
                                native_distance<8.0f ? 1.0f : 0.0f);
        })CL";
        cl_program program=clCreateProgramWithSource(context,1,&source,nullptr,&status);ok(status,"program");
        status=clBuildProgram(program,1,&device,"-cl-mad-enable",nullptr,nullptr);
        if(status!=CL_SUCCESS) {
            char log[16384]={};clGetProgramBuildInfo(program,device,CL_PROGRAM_BUILD_LOG,sizeof(log),log,nullptr);
            std::cerr<<log;ok(status,"build");
        }
        cl_kernel kernel=clCreateKernel(program,"distances",&status);ok(status,"kernel");
        cl_mem in=clCreateBuffer(context,CL_MEM_READ_ONLY|CL_MEM_COPY_HOST_PTR,pairs.size()*sizeof(float),pairs.data(),&status);ok(status,"input buffer");
        cl_mem out=clCreateBuffer(context,CL_MEM_WRITE_ONLY,output.size()*sizeof(float),nullptr,&status);ok(status,"output buffer");
        cl_uint n=static_cast<cl_uint>(count);
        ok(clSetKernelArg(kernel,0,sizeof(in),&in),"arg0");ok(clSetKernelArg(kernel,1,sizeof(out),&out),"arg1");
        ok(clSetKernelArg(kernel,2,sizeof(spacing),&spacing),"arg2");ok(clSetKernelArg(kernel,3,sizeof(n),&n),"arg3");
        size_t local=128, global=((count+local-1)/local)*local;
        ok(clEnqueueNDRangeKernel(queue,kernel,1,nullptr,&global,&local,0,nullptr,nullptr),"launch");
        ok(clEnqueueReadBuffer(queue,out,CL_TRUE,0,output.size()*sizeof(float),output.data(),0,nullptr,nullptr),"read");
        std::ofstream file(argv[2],std::ios::binary);file.write(reinterpret_cast<char*>(output.data()),output.size()*sizeof(float));
        if(!file) throw std::runtime_error("Output write failed");
        clReleaseMemObject(in);clReleaseMemObject(out);clReleaseKernel(kernel);clReleaseProgram(program);
        clReleaseCommandQueue(queue);clReleaseContext(context);
        std::cout<<"Pairs: "<<count<<"; build: -cl-mad-enable; no docking performed\n";
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
