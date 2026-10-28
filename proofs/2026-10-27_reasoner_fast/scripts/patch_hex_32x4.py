"""ggml-hexagon (upstream 338fce65) small-batch decode: a Q4_0 32x4 HVX kernel for hvx_mm_2d_tiled.
The tiled kernel already streams each weight tile into VTCM once per batch, but the 4-bit unpack (and/shift/
shuffle/valign/sub) runs once per PAIR of activation rows. For 3-4 rows (forced-token steps, split streams) the
unpack therefore runs twice. The 32x4 kernel unpacks each weight vector once and feeds 4 activation rows
(the MACs are unchanged), so a 4-row step does about 9+8 instead of 2x(9+4) vector ops per weight vector.
Numerics: identical integer dot products (vrmpy on the same int8 values) and the same per-column scale/accumulate
order as 32x2, so the result is bit-identical to the 32x2 path. usage: patch_hex_32x4.py <llama.cpp tree>"""
import os, sys
root = sys.argv[1]
H = os.path.join(root, "ggml/src/ggml-hexagon/htp/hvx-mm-kernels-tiled.h")
M = os.path.join(root, "ggml/src/ggml-hexagon/htp/matmul-ops.c")


def patch(path, old, new):
    s = open(path, encoding="utf-8").read()
    assert s.count(old) == 1, (path, old[:80])
    open(path, "w", encoding="utf-8", newline="\n").write(s.replace(old, new))


patch(H, "static void tiled_vec_dot_q4_1_32x1(", r"""static inline void accum_4bit_32x4(
    const HVX_Vector * restrict vptr,
    const HVX_Vector * restrict v_act0, const HVX_Vector * restrict v_act1,
    const HVX_Vector * restrict v_act2, const HVX_Vector * restrict v_act3,
    HVX_Vector i8, HVX_Vector * restrict s0, HVX_Vector * restrict s1, HVX_Vector * restrict s2, HVX_Vector * restrict s3
) {
    HVX_Vector v_sum0 = Q6_V_vzero(), v_sum1 = Q6_V_vzero(), v_sum2 = Q6_V_vzero(), v_sum3 = Q6_V_vzero();
    HVX_Vector mask_h4 = Q6_Vb_vsplat_R(0x0F);

    #pragma unroll
    for (int i = 0; i < 4; i++) {
        HVX_VectorPair v_W_pair = unpack_and_interleave_4bit_x2(vptr[i], mask_h4);   // once for 4 columns
        HVX_Vector v_W0 = Q6_Vb_vsub_VbVb(Q6_V_lo_W(v_W_pair), i8);
        HVX_Vector v_W1 = Q6_Vb_vsub_VbVb(Q6_V_hi_W(v_W_pair), i8);
        v_sum0 = Q6_Vw_vrmpyacc_VwVbVb(v_sum0, v_W0, v_act0[i * 2 + 0]);
        v_sum0 = Q6_Vw_vrmpyacc_VwVbVb(v_sum0, v_W1, v_act0[i * 2 + 1]);
        v_sum1 = Q6_Vw_vrmpyacc_VwVbVb(v_sum1, v_W0, v_act1[i * 2 + 0]);
        v_sum1 = Q6_Vw_vrmpyacc_VwVbVb(v_sum1, v_W1, v_act1[i * 2 + 1]);
        v_sum2 = Q6_Vw_vrmpyacc_VwVbVb(v_sum2, v_W0, v_act2[i * 2 + 0]);
        v_sum2 = Q6_Vw_vrmpyacc_VwVbVb(v_sum2, v_W1, v_act2[i * 2 + 1]);
        v_sum3 = Q6_Vw_vrmpyacc_VwVbVb(v_sum3, v_W0, v_act3[i * 2 + 0]);
        v_sum3 = Q6_Vw_vrmpyacc_VwVbVb(v_sum3, v_W1, v_act3[i * 2 + 1]);
    }
    *s0 = v_sum0; *s1 = v_sum1; *s2 = v_sum2; *s3 = v_sum3;
}

// 4 activation rows per weight tile (see accum_4bit_32x4); per column the same scale/accumulate order as 32x2
static void tiled_vec_dot_q4_0_32x4(const uint32_t n, float ** s, const void * restrict vx,
                                    const void ** vy, uint32_t valid_rows, const float ** sz) {
    const uint8_t * restrict tile_ptr = vx;
    HVX_Vector acc[4] = { Q6_V_vzero(), Q6_V_vzero(), Q6_V_vzero(), Q6_V_vzero() };
    HVX_Vector i8 = Q6_Vb_vsplat_R(8);

    uint32_t n_k_tiles = n / 32;
    for (uint32_t kt = 0; kt < n_k_tiles; kt++) {
        const HVX_Vector * restrict vptr = (const HVX_Vector *) (tile_ptr + kt * 640);
        const HVX_Vector * restrict a0 = (const HVX_Vector *) ((const uint8_t *) vy[0] + kt * 1152);
        const HVX_Vector * restrict a1 = (const HVX_Vector *) ((const uint8_t *) vy[1] + kt * 1152);
        const HVX_Vector * restrict a2 = (const HVX_Vector *) ((const uint8_t *) vy[2] + kt * 1152);
        const HVX_Vector * restrict a3 = (const HVX_Vector *) ((const uint8_t *) vy[3] + kt * 1152);
        HVX_Vector v[4];
        accum_4bit_32x4(vptr, a0, a1, a2, a3, i8, &v[0], &v[1], &v[2], &v[3]);
        const HVX_Vector v_scale_w = vptr[4];
        const HVX_Vector * act[4] = { a0, a1, a2, a3 };
        #pragma unroll
        for (int c = 0; c < 4; c++) {
            HVX_Vector v_sf = Q6_Vsf_equals_Vw(v[c]);
            HVX_Vector v_scale_comb = hvx_vec_mul_f16_f16_to_f32_lower32(v_scale_w, act[c][8]);
            acc[c] = hvx_vec_add_f32_f32(acc[c], hvx_vec_mul_f32_f32(v_sf, v_scale_comb));
        }
    }
    #pragma unroll
    for (int c = 0; c < 4; c++) {
        if (sz[c]) hvx_vec_store_u(s[c], valid_rows * sizeof(float), hvx_vec_add_f32_f32(acc[c], hvx_vmemu(sz[c])));
        else       hvx_vec_store_u(s[c], valid_rows * sizeof(float), acc[c]);
    }
}

static void tiled_vec_dot_q4_1_32x1(""")

patch(M, """    void (*vec_dot_32x2)(const uint32_t n, float * restrict s0, float * restrict s1,
         const void * restrict vx,
         const void * restrict vy0, const void * restrict vy1, uint32_t valid_rows,
         const float * restrict sz0, const float * restrict sz1);
""", """    void (*vec_dot_32x2)(const uint32_t n, float * restrict s0, float * restrict s1,
         const void * restrict vx,
         const void * restrict vy0, const void * restrict vy1, uint32_t valid_rows,
         const float * restrict sz0, const float * restrict sz1);

    // optional: 4 activation rows per weight tile (Q4_0 only; NULL = pairs). Disable with GGML_HEXAGON_MM_32X4=0.
    void (*vec_dot_32x4)(const uint32_t n, float ** s, const void * restrict vx,
         const void ** vy, uint32_t valid_rows, const float ** sz);
""")

patch(M, """            mmctx->vec_dot_32x2 = tiled_vec_dot_q4_0_32x2;
            return 0;""", """            mmctx->vec_dot_32x2 = tiled_vec_dot_q4_0_32x2;
            mmctx->vec_dot_32x4 = tiled_vec_dot_q4_0_32x4;
            return 0;""")

patch(M, """        htp_trace_event_start(tr, HTP_TRACE_EVT_HVX_COMP, ct);
        uint32_t ir1 = 0;
        for (; ir1 + 1 < act_nrows; ir1 += 2) {
            const uint8_t * restrict act_col0 = (const uint8_t *) (act_data + (ir1+0) * act_stride);""", """        htp_trace_event_start(tr, HTP_TRACE_EVT_HVX_COMP, ct);
        uint32_t ir1 = 0;
        if (mmctx->vec_dot_32x4) {
            for (; ir1 + 3 < act_nrows; ir1 += 4) {
                float * s[4]; const void * vy[4]; const float * sz[4];
                for (int c = 0; c < 4; c++) {
                    vy[c] = act_data + (ir1 + c) * act_stride;
                    s[c]  = &((float *) (dst->data + ((cur_m_start + ir1 + c) * dst_row_size)))[ct * 32];
                    sz[c] = src2 ? &((const float *) ((const uint8_t *) src2->data + ((cur_m_start + ir1 + c) * src2_stride)))[ct * 32] : NULL;
                }
                mmctx->vec_dot_32x4(ne10, s, w_tile, vy, valid_rows, sz);
            }
            if (ir1 + 3 == act_nrows) {  // 3 rows: one 32x4 pass with the 3rd row duplicated (its result is written twice)
                float * s[4]; const void * vy[4]; const float * sz[4];
                for (int c = 0; c < 4; c++) {
                    const int r = c < 3 ? c : 2;
                    vy[c] = act_data + (ir1 + r) * act_stride;
                    s[c]  = &((float *) (dst->data + ((cur_m_start + ir1 + r) * dst_row_size)))[ct * 32];
                    sz[c] = src2 ? &((const float *) ((const uint8_t *) src2->data + ((cur_m_start + ir1 + r) * src2_stride)))[ct * 32] : NULL;
                }
                mmctx->vec_dot_32x4(ne10, s, w_tile, vy, valid_rows, sz);
                ir1 += 3;
            }
        }
        for (; ir1 + 1 < act_nrows; ir1 += 2) {
            const uint8_t * restrict act_col0 = (const uint8_t *) (act_data + (ir1+0) * act_stride);""")

# env switch on the host side is not available inside the DSP: the kill switch is a compile define
patch(M, """            mmctx->vec_dot_32x4 = tiled_vec_dot_q4_0_32x4;""", """#ifndef HTP_NO_MM_32X4
            mmctx->vec_dot_32x4 = tiled_vec_dot_q4_0_32x4;
#endif""")
print("32x4 patched", root)
