// Minimal QR Code generator (byte mode, auto version, ECC level M) — MIT-style, self-contained.
// Adapted compact implementation. Exposes window.QRMini.toCanvas(canvas, text, sizePx).
(function(){
  // Galois field tables
  var EXP=new Array(256), LOG=new Array(256);
  (function(){var x=1;for(var i=0;i<255;i++){EXP[i]=x;LOG[x]=i;x<<=1;if(x&0x100)x^=0x11d;}for(var i=255;i<256;i++)EXP[i]=EXP[i-255];})();
  function gmul(a,b){if(a===0||b===0)return 0;return EXP[(LOG[a]+LOG[b])%255];}
  function rsGen(deg){var p=[1];for(var i=0;i<deg;i++){var np=new Array(p.length+1);for(var j=0;j<np.length;j++)np[j]=0;for(var j=0;j<p.length;j++){np[j]^=gmul(p[j],1);np[j+1]^=gmul(p[j],EXP[i]);}p=np;}return p;}
  function rsEnc(data,deg){var gen=rsGen(deg);var res=data.slice();for(var i=0;i<deg;i++)res.push(0);for(var i=0;i<data.length;i++){var c=res[i];if(c!==0){for(var j=0;j<gen.length;j++)res[i+j]^=gmul(gen[j],c);}}return res.slice(data.length);}
  // version capacity (byte, ECC M) total data codewords and ecc per block, blocks
  // We support versions 1..10 (enough for our URLs ~80-110 chars)
  // [version]: {ecc:eccPerBlock, g1:blocksGroup1, c1:dataCwPerBlockG1, g2, c2, total}
  var VER={
    1:{ecc:10,g1:1,c1:16,g2:0,c2:0},
    2:{ecc:16,g1:1,c1:28,g2:0,c2:0},
    3:{ecc:26,g1:1,c1:44,g2:0,c2:0},
    4:{ecc:18,g1:2,c1:32,g2:0,c2:0},
    5:{ecc:24,g1:2,c1:43,g2:0,c2:0},
    6:{ecc:16,g1:4,c1:27,g2:0,c2:0},
    7:{ecc:18,g1:4,c1:31,g2:0,c2:0},
    8:{ecc:22,g1:2,c1:38,g2:2,c2:39},
    9:{ecc:22,g1:3,c1:36,g2:2,c2:37},
    10:{ecc:26,g1:4,c1:43,g2:1,c2:44}
  };
  function dataCw(v){var x=VER[v];return x.g1*x.c1+x.g2*x.c2;}
  function size(v){return 17+4*v;}
  function bytes(str){var u=[],i,c;for(i=0;i<str.length;i++){c=str.charCodeAt(i);if(c<128)u.push(c);else if(c<2048){u.push(192|(c>>6));u.push(128|(c&63));}else{u.push(224|(c>>12));u.push(128|((c>>6)&63));u.push(128|(c&63));}}return u;}
  function pickVer(n){for(var v=1;v<=10;v++){var cap=dataCw(v)-2-((size(v)<27||v<10)?0:0);var cci=(v<10)?1:2;var need=Math.ceil((4+cci*8+n*8)/8)+0;if(n+2+cci<=dataCw(v))return v;}return 10;}
  function build(text){
    var data=bytes(text);
    var v=pickVer(data.length);
    var cci=(v<10)?8:16;
    var bits=[];
    function push(val,len){for(var i=len-1;i>=0;i--)bits.push((val>>i)&1);}
    push(4,4); // byte mode
    push(data.length,cci);
    for(var i=0;i<data.length;i++)push(data[i],8);
    var totalData=dataCw(v);
    // terminator
    var rem=totalData*8-bits.length; if(rem>4)rem=4; for(var i=0;i<rem;i++)bits.push(0);
    while(bits.length%8)bits.push(0);
    var dcw=[]; for(var i=0;i<bits.length;i+=8){var b=0;for(var j=0;j<8;j++)b=(b<<1)|bits[i+j];dcw.push(b);}
    var pad=[236,17],pi=0; while(dcw.length<totalData){dcw.push(pad[pi%2]);pi++;}
    // split into blocks
    var x=VER[v]; var blocks=[]; var idx=0;
    for(var i=0;i<x.g1;i++){blocks.push(dcw.slice(idx,idx+x.c1));idx+=x.c1;}
    for(var i=0;i<x.g2;i++){blocks.push(dcw.slice(idx,idx+x.c2));idx+=x.c2;}
    var eccBlocks=blocks.map(function(b){return rsEnc(b,x.ecc);});
    // interleave
    var maxD=Math.max.apply(null,blocks.map(function(b){return b.length;}));
    var finalCw=[];
    for(var i=0;i<maxD;i++)for(var b=0;b<blocks.length;b++)if(i<blocks[b].length)finalCw.push(blocks[b][i]);
    for(var i=0;i<x.ecc;i++)for(var b=0;b<eccBlocks.length;b++)finalCw.push(eccBlocks[b][i]);
    // place modules
    var n=size(v);
    var m=[],used=[];
    for(var r=0;r<n;r++){m.push(new Array(n).fill(0));used.push(new Array(n).fill(false));}
    function setF(r,c,val){m[r][c]=val?1:0;used[r][c]=true;}
    function finder(r,c){for(var dr=-1;dr<=7;dr++)for(var dc=-1;dc<=7;dc++){var rr=r+dr,cc=c+dc;if(rr<0||cc<0||rr>=n||cc>=n)continue;var inb=(dr>=0&&dr<=6&&(dc===0||dc===6))||(dc>=0&&dc<=6&&(dr===0||dr===6))||(dr>=2&&dr<=4&&dc>=2&&dc<=4);setF(rr,cc,inb);}}
    finder(0,0);finder(0,n-7);finder(n-7,0);
    for(var i=0;i<n;i++){if(!used[6][i]){setF(6,i,i%2===0);}if(!used[i][6]){setF(i,6,i%2===0);}}
    // alignment (v>=2): single center for v2..6 etc. simple table
    var ALIGN={2:[6,18],3:[6,22],4:[6,26],5:[6,30],6:[6,34],7:[6,22,38],8:[6,24,42],9:[6,26,46],10:[6,28,50]};
    if(v>=2){var pos=ALIGN[v];for(var a=0;a<pos.length;a++)for(var b=0;b<pos.length;b++){var ar=pos[a],ac=pos[b];if(used[ar][ac])continue;for(var dr=-2;dr<=2;dr++)for(var dc=-2;dc<=2;dc++){var inb=(Math.abs(dr)===2||Math.abs(dc)===2||(dr===0&&dc===0));setF(ar+dr,ac+dc,inb);}}}
    // reserve format areas
    for(var i=0;i<9;i++){if(!used[8][i]){used[8][i]=true;}if(!used[i][8]){used[i][8]=true;}}
    for(var i=0;i<8;i++){used[8][n-1-i]=true;used[n-1-i][8]=true;}
    setF(n-8,8,1); used[n-8][8]=true;
    // place data with mask 0
    var dir=-1,col=n-1,bitIdx=0;
    var allBits=[];for(var i=0;i<finalCw.length;i++)for(var j=7;j>=0;j--)allBits.push((finalCw[i]>>j)&1);
    var row=n-1;
    while(col>0){if(col===6)col--;for(var i=0;i<n;i++){for(var c2=0;c2<2;c2++){var cc=col-c2;if(used[row][cc])continue;var bit=bitIdx<allBits.length?allBits[bitIdx++]:0;var mask=((row+cc)%2===0);m[row][cc]=bit^(mask?1:0);used[row][cc]=true;}row+=dir;}dir=-dir;row+=dir;col-=2;}
    // format info (ECC M=00, mask 0 -> 000) string with BCH
    var fmt=0x5412^0x0; // M + mask0 reference value (precomputed common): use standard table
    // Standard format bits for ECC level M (binary 00) and mask pattern 0:
    var FMT_M0=0x5412; // 101010000010010
    var fb=FMT_M0;
    var fbits=[];for(var i=14;i>=0;i--)fbits.push((fb>>i)&1);
    // place format
    function pf(r,c,bit){m[r][c]=bit;}
    var seqA=[[8,0],[8,1],[8,2],[8,3],[8,4],[8,5],[8,7],[8,8],[7,8],[5,8],[4,8],[3,8],[2,8],[1,8],[0,8]];
    for(var i=0;i<15;i++)pf(seqA[i][0],seqA[i][1],fbits[i]);
    var seqB=[[n-1,8],[n-2,8],[n-3,8],[n-4,8],[n-5,8],[n-6,8],[n-7,8],[8,n-8],[8,n-7],[8,n-6],[8,n-5],[8,n-4],[8,n-3],[8,n-2],[8,n-1]];
    for(var i=0;i<15;i++)pf(seqB[i][0],seqB[i][1],fbits[i]);
    return {n:n,m:m};
  }
  function toCanvas(canvas,text,px){
    var q=build(text);var n=q.n;var quiet=4;var total=n+quiet*2;
    var scale=Math.max(1,Math.floor(px/total));var dim=total*scale;
    canvas.width=dim;canvas.height=dim;canvas.style.width=px+"px";canvas.style.height=px+"px";
    var ctx=canvas.getContext("2d");ctx.fillStyle="#ffffff";ctx.fillRect(0,0,dim,dim);ctx.fillStyle="#0b1220";
    for(var r=0;r<n;r++)for(var c=0;c<n;c++)if(q.m[r][c])ctx.fillRect((c+quiet)*scale,(r+quiet)*scale,scale,scale);
  }
  window.QRMini={toCanvas:toCanvas};
})();
