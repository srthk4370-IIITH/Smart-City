// fincore: % of each file resident in the page cache (mincore). Read-only; no NPU. Also: -r = time a full read.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
static double now(){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
int main(int argc,char**argv){
  int rd=0;
  for(int i=1;i<argc;i++){
    if(!strcmp(argv[i],"-r")){rd=1;continue;}
    int fd=open(argv[i],O_RDONLY); if(fd<0){perror(argv[i]);continue;}
    struct stat st; fstat(fd,&st); size_t ps=sysconf(_SC_PAGESIZE), np=(st.st_size+ps-1)/ps;
    void*m=mmap(0,st.st_size,PROT_READ,MAP_SHARED,fd,0); unsigned char*v=malloc(np); size_t r=0;
    if(m!=MAP_FAILED && mincore(m,st.st_size,v)==0) for(size_t k=0;k<np;k++) r+=v[k]&1;
    printf("%s: %.1f%% resident (%zu/%zu pages, %.0f MB)",argv[i],100.0*r/np,r,np,st.st_size/1048576.0);
    if(rd){ static char buf[8<<20]; double t=now(); ssize_t n; size_t tot=0; while((n=read(fd,buf,sizeof buf))>0) tot+=n; double dt=now()-t; printf(", read %.0f MB in %.0f ms (%.2f GB/s)",tot/1048576.0,dt*1e3,tot/dt/1e9);}
    printf("\n"); if(m!=MAP_FAILED) munmap(m,st.st_size); close(fd); free(v);
  }
  return 0;
}
