package com.iiith.smartcityedge;

import android.util.Base64;

import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.math.BigInteger;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.PrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;

import javax.crypto.Cipher;

/**
 * Minimal adb client for the QIDK's OWN adb daemon on 127.0.0.1:5555.
 *
 * Why: on this QIDK firmware ordinary apps may not open the Hexagon NPU (the vendor DSP service
 * returns EACCES), but the shell user may. The app therefore asks the local adbd - which runs as the
 * shell user - to start the NPU backend, so nothing needs a laptop, even after a reboot.
 * Requires persist.adb.tcp.port=5555 (set once, see HANDBOOK). Supports RSA AUTH in case adb
 * authorization is enabled; this dev kit has ro.adb.secure unset, so adbd accepts without a prompt.
 */
public final class AdbLocal {
    private static final int A_CNXN = 0x4e584e43, A_AUTH = 0x48545541, A_OPEN = 0x4e45504f,
            A_OKAY = 0x59414b4f, A_CLSE = 0x45534c43, A_WRTE = 0x45545257;
    private static final int VERSION = 0x01000001, MAXDATA = 256 * 1024;

    private final File keyDir;

    public AdbLocal(File keyDir) {
        this.keyDir = keyDir;
    }

    /** Runs a shell command as the adb shell user; returns its output (blocks until the command exits). */
    public String shell(String cmd, int timeoutMs) throws Exception {
        try (Socket s = new Socket()) {
            s.connect(new InetSocketAddress("127.0.0.1", 5555), 2000);
            s.setSoTimeout(timeoutMs);
            DataInputStream in = new DataInputStream(s.getInputStream());
            OutputStream out = s.getOutputStream();
            send(out, A_CNXN, VERSION, MAXDATA, "host::\0".getBytes(StandardCharsets.UTF_8));
            boolean sentSig = false;
            while (true) {
                Msg m = read(in);
                if (m.cmd == A_CNXN) break;
                if (m.cmd != A_AUTH) throw new IllegalStateException("unexpected adb reply " + Integer.toHexString(m.cmd));
                KeyPair kp = keys();
                if (!sentSig) { // type 2 = SIGNATURE of the 20-byte token
                    send(out, A_AUTH, 2, 0, sign(kp.getPrivate(), m.data));
                    sentSig = true;
                } else {        // type 3 = public key; adbd shows "Allow USB debugging?" once
                    send(out, A_AUTH, 3, 0, (androidPubKey((RSAPublicKey) kp.getPublic()) + " smartcityedge@qidk\0")
                            .getBytes(StandardCharsets.UTF_8));
                }
            }
            int local = 1;
            send(out, A_OPEN, local, 0, ("shell:" + cmd + "\0").getBytes(StandardCharsets.UTF_8));
            ByteArrayOutputStream result = new ByteArrayOutputStream();
            while (true) {
                Msg m = read(in);
                if (m.cmd == A_WRTE) {
                    result.write(m.data);
                    send(out, A_OKAY, local, m.arg0, new byte[0]);
                } else if (m.cmd == A_CLSE) {
                    send(out, A_CLSE, local, m.arg0, new byte[0]);
                    return result.toString("UTF-8");
                }
                // A_OKAY: stream opened / write acknowledged
            }
        }
    }

    public static boolean listening() {
        try (Socket s = new Socket()) {
            s.connect(new InetSocketAddress("127.0.0.1", 5555), 1000);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    // ------------------------------------------------------------------------------- wire format
    private static final class Msg {
        int cmd, arg0, arg1;
        byte[] data;
    }

    private static void send(OutputStream out, int cmd, int a0, int a1, byte[] data) throws Exception {
        ByteBuffer h = ByteBuffer.allocate(24).order(ByteOrder.LITTLE_ENDIAN);
        int sum = 0;
        for (byte b : data) sum += b & 0xff;
        h.putInt(cmd).putInt(a0).putInt(a1).putInt(data.length).putInt(sum).putInt(~cmd);
        out.write(h.array());
        out.write(data);
        out.flush();
    }

    private static Msg read(DataInputStream in) throws Exception {
        byte[] hb = new byte[24];
        in.readFully(hb);
        ByteBuffer h = ByteBuffer.wrap(hb).order(ByteOrder.LITTLE_ENDIAN);
        Msg m = new Msg();
        m.cmd = h.getInt();
        m.arg0 = h.getInt();
        m.arg1 = h.getInt();
        int len = h.getInt();
        m.data = new byte[len];
        in.readFully(m.data);
        return m;
    }

    // ------------------------------------------------------------------------------- RSA auth
    private KeyPair keys() throws Exception {
        File pri = new File(keyDir, "adbkey.pk8"), pub = new File(keyDir, "adbkey.x509");
        KeyFactory kf = KeyFactory.getInstance("RSA");
        if (pri.exists() && pub.exists()) {
            return new KeyPair(kf.generatePublic(new X509EncodedKeySpec(readAll(pub))),
                    kf.generatePrivate(new PKCS8EncodedKeySpec(readAll(pri))));
        }
        KeyPairGenerator g = KeyPairGenerator.getInstance("RSA");
        g.initialize(2048);
        KeyPair kp = g.generateKeyPair();
        try (FileOutputStream o = new FileOutputStream(pri)) { o.write(kp.getPrivate().getEncoded()); }
        try (FileOutputStream o = new FileOutputStream(pub)) { o.write(kp.getPublic().getEncoded()); }
        return kp;
    }

    private static byte[] readAll(File f) throws Exception {
        try (FileInputStream i = new FileInputStream(f)) {
            return i.readAllBytes();
        }
    }

    /** adbd verifies RSA_verify(NID_sha1, token): PKCS#1 v1.5 over SHA-1 DigestInfo prefix + token. */
    private static byte[] sign(PrivateKey k, byte[] token) throws Exception {
        byte[] prefix = {0x30, 0x21, 0x30, 0x09, 0x06, 0x05, 0x2b, 0x0e, 0x03, 0x02, 0x1a, 0x05, 0x00, 0x04, 0x14};
        byte[] msg = new byte[prefix.length + token.length];
        System.arraycopy(prefix, 0, msg, 0, prefix.length);
        System.arraycopy(token, 0, msg, prefix.length, token.length);
        Cipher c = Cipher.getInstance("RSA/ECB/PKCS1Padding");
        c.init(Cipher.ENCRYPT_MODE, k);
        return c.doFinal(msg);
    }

    /** Android's mincrypt RSAPublicKey layout, base64 (what ~/.android/adbkey.pub contains). */
    private static String androidPubKey(RSAPublicKey k) {
        int words = 64; // 2048-bit
        BigInteger n = k.getModulus(), r32 = BigInteger.ONE.shiftLeft(32);
        BigInteger n0inv = n.mod(r32).modInverse(r32).negate().mod(r32);
        BigInteger rr = BigInteger.ONE.shiftLeft(2048 * 2).mod(n);
        ByteBuffer b = ByteBuffer.allocate(4 + 4 + words * 4 * 2 + 4).order(ByteOrder.LITTLE_ENDIAN);
        b.putInt(words).putInt(n0inv.intValue());
        for (int i = 0; i < words; i++) b.putInt(n.shiftRight(32 * i).mod(r32).intValue());
        for (int i = 0; i < words; i++) b.putInt(rr.shiftRight(32 * i).mod(r32).intValue());
        b.putInt(k.getPublicExponent().intValue());
        return Base64.encodeToString(b.array(), Base64.NO_WRAP);
    }
}
